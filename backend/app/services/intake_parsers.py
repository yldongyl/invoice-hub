# -*- coding: utf-8 -*-
"""受理层载体探测与结构化抽取（FN-1-05①/③ · WP3.1）。

纪律与边界：
  - 全部为确定性判断（依赖纪律⑥，无模型推断）：文件头魔数、zip/pdf 结构探测、XML/UBL 解析、
    PDF 文本层抽取与票面字段正则——属「平台内置解析能力（非 Provider、非自研 OCR）」（清单 §3.1 层边界）；
  - 演示口径（P00 §6）：数电票 EInvoice 命名空间按 seeds/cases.json source_xml 同构解析；
    完整 23 字段 + 票面 Schema 全量校验属 FN-2-01（M4），本模块只抽取受理派生所需关键字段；
    PDF 文本层抽取为轻量探测（流解压 + Tj 文本 + 正则），OFD 按 zip 解包找内嵌 XML。
"""

import io
import re
import zipfile
import zlib
import xml.etree.ElementTree as ET

KINDS = ("xml", "ofd", "pdf", "image", "corrupt")


def _local(tag: str) -> str:
    """剥离命名空间前缀取本地名。"""
    return tag.split("}")[-1]


def detect_kind(content: bytes) -> dict:
    """①信封解析机判据：文件头魔数 + 结构探测（不含语义判定）。"""
    head = content[:8]
    flags = {
        "header_ok": False, "kind": "corrupt",
        "is_zip": head[:2] == b"PK", "pdf_encrypt": False, "has_text_layer": False,
        "xml_parseable": False,
    }
    if head.startswith(b"%PDF-"):
        flags.update(header_ok=True, kind="pdf", pdf_encrypt=b"/Encrypt" in content[:200000])
        flags["has_text_layer"] = bool(extract_pdf_text(content))
    elif head[:2] == b"PK":
        flags.update(header_ok=True, kind="ofd")
    elif head.startswith(b"\xff\xd8") or head.startswith(b"\x89PNG"):
        flags.update(header_ok=True, kind="image")
    else:
        # XML/文本类：以可解析性为准
        text = _decode_head(content)
        if re.search(r"<\s*\?xml|<\s*\w+", text):
            flags.update(header_ok=True, kind="xml", xml_parseable=_xml_parseable(content))
    return flags


def _decode_head(content: bytes, limit: int = 400000) -> str:
    for enc in ("utf-8", "gb18030"):
        try:
            return content[:limit].decode(enc, errors="ignore")
        except LookupError:  # pragma: no cover
            continue
    return content[:limit].decode("utf-8", errors="ignore")


def _xml_parseable(content: bytes) -> bool:
    try:
        ET.fromstring(content.decode("utf-8", errors="ignore"))
        return True
    except (ET.ParseError, UnicodeDecodeError):
        return False


def extract_pdf_text(content: bytes) -> str:
    """PDF 文本层轻量探测：解压 Flate 流，取 (string) Tj/TJ 操作符文本（演示口径）。"""
    chunks: list[str] = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", content, re.S):
        raw = m.group(1)
        try:
            data = zlib.decompress(raw)
        except zlib.error:
            data = raw if b"(" in raw[:200] else b""
        if not data:
            continue
        txt = data.decode("latin-1", errors="ignore")
        chunks += re.findall(r"\((?:\\.|[^)\\])*\)", txt)
    joined = " ".join(c.strip("()") for c in chunks)
    return joined if len(joined) >= 24 else ""      # 少于 24 字符判无有效文本层


def text_head(content: bytes, kind: str) -> str:
    """非发票过滤与正则抽取共用的文本头部（确定性输入）。"""
    if kind == "pdf":
        return extract_pdf_text(content)[:4000]
    return _decode_head(content, 60000)[:4000]


# ───────────────────────── 数电票 EInvoice XML（与 seeds source_xml 同构） ─────────────────────────

def parse_einvoice_xml(content: bytes) -> dict | None:
    """解析数电票 XML 关键节点；结构不符返回 None（派生失败→人工分拣兜底注记）。"""
    try:
        root = ET.fromstring(_decode_head(content, 2_000_000))
    except ET.ParseError:
        return None
    idx = {}
    for el in root.iter():
        idx.setdefault(_local(el.tag), el)
    def g(path_tag):
        el = idx.get(path_tag)
        return (el.text or "").strip() if el is not None else None
    doc = {
        "invoice_no": g("InvoiceNo"), "issue_date": g("IssueDate"),
        "invoice_type": g("InvoiceType") or "数电票",
        "seller_name": g("Name"), "seller_tax_id": None, "buyer_name": None, "buyer_tax_id": None,
        "net": _num(g("NetAmount")), "tax": _num(g("TaxAmount")), "gross": _num(g("GrossAmount")),
        "currency": "CNY", "lines": [], "xml": _decode_head(content, 2_000_000),
        "ns": "einvoice",
    }
    if doc["invoice_no"] is None:
        return None                                    # 非目标票面结构
    seller = next((e for e in root.iter() if _local(e.tag) == "Seller"), None)
    buyer = next((e for e in root.iter() if _local(e.tag) == "Buyer"), None)
    if seller is not None:
        for c in seller:
            t = _local(c.tag)
            if t == "Name":
                doc["seller_name"] = (c.text or "").strip()
            elif t == "TaxID":
                doc["seller_tax_id"] = (c.text or "").strip()
    if buyer is not None:
        for c in buyer:
            t = _local(c.tag)
            if t == "Name":
                doc["buyer_name"] = (c.text or "").strip()
            elif t == "TaxID":
                doc["buyer_tax_id"] = (c.text or "").strip()
    items = next((e for e in root.iter() if _local(e.tag) == "Items"), None)
    if items is not None:
        for it in items:
            if _local(it.tag) != "Item":
                continue
            row = {"line": it.get("lineNo"), "name": None, "amount": None, "qty": None,
                   "price": None, "tax_rate": None}
            for c in it:
                t = _local(c.tag)
                if t == "Name":
                    row["name"] = (c.text or "").strip()
                elif t in ("Amount", "Qty", "Price", "TaxRate"):
                    row[{"Amount": "amount", "Qty": "qty", "Price": "price",
                         "TaxRate": "tax_rate"}[t]] = _num(c.text)
            doc["lines"].append(row)
    return doc


# ───────────────────────── 海外 UBL/Peppol 极简解析（DOX 演示桩） ─────────────────────────

def parse_ubl_minimal(content: bytes) -> dict | None:
    """UBL Invoice 关键节点极简抽取（演示口径；完整 e-invoicing 适配归 M4 海外 Provider 域）。"""
    try:
        root = ET.fromstring(_decode_head(content, 2_000_000))
    except ET.ParseError:
        return None
    idx = {}
    for el in root.iter():
        idx.setdefault(_local(el.tag), el)
    def g(tag):
        el = idx.get(tag)
        return (el.text or "").strip() if el is not None else None
    no = g("ID")
    if no is None:
        return None
    doc = {
        "invoice_no": no, "issue_date": (g("IssueDate") or "")[:10],
        "invoice_type": g("InvoiceTypeCode") or "Supplier Invoice（海外）",
        "seller_name": None, "seller_tax_id": None, "buyer_name": None, "buyer_tax_id": None,
        "net": _num(g("TaxExclusiveAmount")), "tax": _num(g("TaxAmount")),
        "gross": _num(g("PayableAmount")), "currency": g("DocumentCurrencyCode") or "SGD",
        "lines": [], "xml": _decode_head(content, 2_000_000), "ns": "ubl",
    }
    sup = next((e for e in root.iter() if _local(e.tag) == "AccountingSupplierParty"), None)
    buy = next((e for e in root.iter() if _local(e.tag) == "AccountingCustomerParty"), None)
    for party, kn, kt in ((sup, "seller_name", "seller_tax_id"), (buy, "buyer_name", "buyer_tax_id")):
        if party is None:
            continue
        for el in party.iter():
            t = _local(el.tag)
            if t == "Name" and doc[kn] is None:
                doc[kn] = (el.text or "").strip()
            elif t in ("TaxID", "CompanyID") and doc[kt] is None:
                doc[kt] = (el.text or "").strip()
    return doc if doc["gross"] is not None else None


def parse_pdf_fields(text: str) -> dict | None:
    """PDF 文本层字段正则抽取（演示口径最小集；FN-2-01 完整抽取归 M4）。"""
    no = re.search(r"(?<!\d)(\d{8,20})(?!\d)", text)
    gross = re.search(r"(?:价税合计|合计|Total(?:\s*\(Gross\))?)\D{0,12}([0-9,]+\.[0-9]{2})", text, re.I)
    if not no or not gross:
        return None
    date = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    tax = re.search(r"(?:税额|Tax(?:\s*Amount)?|GST)\D{0,12}([0-9,]+\.[0-9]{2})", text, re.I)
    net = re.search(r"(?:净额|不含税|Net(?:\s*Amount)?|Tax\s*Exclusive)\D{0,12}([0-9,]+\.[0-9]{2})", text, re.I)
    cur = "SGD" if re.search(r"S\$|SGD", text) else ("USD" if re.search(r"US\$|USD", text) else "CNY")
    def num(s):
        return float(s.replace(",", "")) if s else None
    return {
        "invoice_no": no.group(1),
        "issue_date": f"{date.group(1)}-{int(date.group(2)):02d}-{int(date.group(3)):02d}" if date else None,
        "invoice_type": "增值税票（PDF 文本层）" if cur == "CNY" else "Supplier Invoice（PDF 文本层）",
        "seller_name": None, "seller_tax_id": None, "buyer_name": None, "buyer_tax_id": None,
        "net": num(net.group(1) if net else None), "tax": num(tax.group(1) if tax else None),
        "gross": num(gross.group(1)), "currency": cur, "lines": [], "xml": None, "ns": "pdf_text",
    }


def _num(s):
    if s is None:
        return None
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def amount_display(currency: str | None, gross: float | None) -> str:
    """meta.amount_display 页面口径（负数红字票保留负号，FN-0-15）。"""
    if gross is None:
        return "—"
    sym = {"CNY": "¥", "SGD": "S$", "USD": "US$"}.get(currency or "", (currency or "") + " ")
    return f"{sym}{gross:,.2f}"
