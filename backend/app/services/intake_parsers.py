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
    """PDF 文本层轻量抽取：解压 Flate 流，解析 ToUnicode CMap 字符映射与 (string) Tj/TJ 文本（兼顾 CID 与普通字体）。"""
    streams: list[bytes] = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", content, re.S):
        raw = m.group(1)
        try:
            streams.append(zlib.decompress(raw))
        except zlib.error:
            if b"(" in raw[:200]:
                streams.append(raw)

    # 1. 解析 PDF 内嵌的 ToUnicode CMaps（国标发票 / CID 字体规范）
    cmap: dict[int, str] = {}
    for s in streams:
        if b"beginbfrange" in s:
            t = s.decode("latin-1", errors="ignore")
            for start, end, target_hex in re.findall(r"<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>", t):
                s_val = int(start, 16)
                e_val = int(end, 16)
                t_val = int(target_hex, 16)
                for cid in range(s_val, e_val + 1):
                    cmap[cid] = chr(t_val + (cid - s_val))
        if b"beginbfchar" in s:
            t = s.decode("latin-1", errors="ignore")
            for src, dst in re.findall(r"<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>", t):
                cmap[int(src, 16)] = chr(int(dst, 16))

    def decode_tj_bytes(data: bytes) -> str:
        if not cmap:
            return data.decode("latin-1", errors="ignore")
        out = []
        i = 0
        while i < len(data):
            if i + 1 < len(data):
                cid2 = (data[i] << 8) | data[i+1]
                if cid2 in cmap:
                    out.append(cmap[cid2])
                    i += 2
                    continue
            cid1 = data[i]
            if cid1 in cmap:
                out.append(cmap[cid1])
            else:
                out.append(chr(cid1) if 32 <= cid1 <= 126 else " ")
            i += 1
        return "".join(out)

    chunks: list[str] = []
    for s in streams:
        pos = 0
        while pos < len(s):
            if s[pos] == 40:  # b'('
                end = pos + 1
                buf = []
                while end < len(s):
                    if s[end] == 92 and end + 1 < len(s):  # b'\\'
                        buf.append(s[end+1])
                        end += 2
                    elif s[end] == 41:  # b')'
                        break
                    else:
                        buf.append(s[end])
                        end += 1
                chunks.append(decode_tj_bytes(bytes(buf)))
                pos = end + 1
            else:
                pos += 1
    joined = " ".join(chunks)
    return joined if len(joined) >= 24 else ""      # 少于 24 字符判无有效文本层


def text_head(content: bytes, kind: str) -> str:
    """非发票过滤与正则抽取共用的文本头部（确定性输入）。"""
    if kind == "pdf":
        return extract_pdf_text(content)[:4000]
    return _decode_head(content, 60000)[:4000]


# ───────────────────────── 数电票 EInvoice XML（与 seeds source_xml 同构） ─────────────────────────

def parse_einvoice_xml(content: bytes) -> dict | None:
    """解析数电票 XML 关键节点（兼顾平台样例 Schema 与税务局国标 SWEI2102 数电票规范）。"""
    try:
        root = ET.fromstring(_decode_head(content, 2_000_000))
    except ET.ParseError:
        return None
    idx = {}
    for el in root.iter():
        idx.setdefault(_local(el.tag), el)
    def g(*tags):
        for path_tag in tags:
            el = idx.get(path_tag)
            if el is not None and (el.text or "").strip():
                return el.text.strip()
        return None

    # 发票号码：样例 InvoiceNo 或 国标 EIid / InvoiceNumber
    invoice_no = g("InvoiceNo", "EIid", "InvoiceNumber")
    if not invoice_no:
        return None

    # 开票日期：样例 IssueDate 或 国标 IssueTime / InvoicingTime / EIissuDate / RequestTime
    issue_date = g("IssueDate", "IssueTime", "EIissuDate", "InvoicingTime", "RequestTime")
    if issue_date and len(issue_date) >= 10:
        issue_date = issue_date[:10]

    # 金额字段：样例 GrossAmount / NetAmount / TaxAmount
    # 国标全电：TotalTax-includedAmount / TotalAmWithoutTax / TotalTaxAm
    gross_val = g("GrossAmount", "TotalTax-includedAmount", "TotalTaxIncludedAmount", "TotaltaxIncludedAmount")
    net_val = g("NetAmount", "TotalAmWithoutTax", "AmountWithoutTax")
    tax_val = g("TaxAmount", "TotalTaxAm", "TaxAm")

    seller_name = g("SellerName")
    seller_tax_id = g("SellerIdNum")
    buyer_name = g("BuyerName")
    buyer_tax_id = g("BuyerIdNum")

    seller = next((e for e in root.iter() if _local(e.tag) == "Seller"), None)
    buyer = next((e for e in root.iter() if _local(e.tag) == "Buyer"), None)
    if seller is not None:
        for c in seller:
            t = _local(c.tag)
            if t == "Name" and not seller_name:
                seller_name = (c.text or "").strip()
            elif t in ("TaxID", "TaxId", "IdNum") and not seller_tax_id:
                seller_tax_id = (c.text or "").strip()
    if buyer is not None:
        for c in buyer:
            t = _local(c.tag)
            if t == "Name" and not buyer_name:
                buyer_name = (c.text or "").strip()
            elif t in ("TaxID", "TaxId", "IdNum") and not buyer_tax_id:
                buyer_tax_id = (c.text or "").strip()

    doc = {
        "invoice_no": invoice_no,
        "issue_date": issue_date,
        "invoice_type": g("InvoiceType") or "数电票",
        "seller_name": seller_name or g("Name"),
        "seller_tax_id": seller_tax_id,
        "buyer_name": buyer_name,
        "buyer_tax_id": buyer_tax_id,
        "net": _num(net_val),
        "tax": _num(tax_val),
        "gross": _num(gross_val),
        "currency": "CNY",
        "lines": [],
        "xml": _decode_head(content, 2_000_000),
        "ns": "einvoice",
    }

    # 行项目解析：① 样例 <Items><Item>；② 国标 SWEI2102 <IssuItemInformation>
    line_no = 1
    items = next((e for e in root.iter() if _local(e.tag) == "Items"), None)
    if items is not None:
        for it in items:
            if _local(it.tag) != "Item":
                continue
            row = {"line": it.get("lineNo") or str(line_no), "name": None, "amount": None, "qty": None,
                   "price": None, "tax_rate": None}
            for c in it:
                t = _local(c.tag)
                if t == "Name":
                    row["name"] = (c.text or "").strip()
                elif t in ("Amount", "Qty", "Price", "TaxRate"):
                    row[{"Amount": "amount", "Qty": "qty", "Price": "price",
                         "TaxRate": "tax_rate"}[t]] = _num(c.text)
            doc["lines"].append(row)
            line_no += 1
    else:
        for el in root.iter():
            if _local(el.tag) in ("IssuItemInformation", "ItemInformation"):
                row = {"line": str(line_no), "name": None, "amount": None, "qty": None,
                       "price": None, "tax_rate": None}
                for c in el:
                    t = _local(c.tag)
                    if t in ("ItemName", "Name"):
                        row["name"] = (c.text or "").strip()
                    elif t in ("Quantity", "Qty"):
                        row["qty"] = _num(c.text)
                    elif t in ("UnPrice", "Price", "UnitPrice"):
                        row["price"] = _num(c.text)
                    elif t in ("Amount", "AmWithoutTax"):
                        row["amount"] = _num(c.text)
                    elif t == "TaxRate":
                        row["tax_rate"] = _num(c.text)
                if row["name"] or row["amount"] is not None:
                    doc["lines"].append(row)
                    line_no += 1

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
    """PDF 文本层字段正则抽取（兼顾海外 Supplier Invoice 与中国数电票/专票版式）。"""
    no = re.search(r"(?<!\d)(\d{8,20})(?!\d)", text)
    # 兼顾普通英文合计、中文价税合计、及（小写）¥108.16 等国内数电票版式
    gross = re.search(r"(?:价税(?:[合计\s\[\]]*)|(?:小写[）\)]*)|Total(?:\s*\(Gross\))?)\D{0,12}([0-9,]+\.[0-9]{2})", text, re.I)
    if not no or not gross:
        return None
    date = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    tax = re.search(r"(?:税\s*额|Tax(?:\s*Amount)?|GST)\D{0,12}([0-9,]+\.[0-9]{2})", text, re.I)
    net = re.search(r"(?:净额|不含税|合计|[^\w]计|Net(?:\s*Amount)?|Tax\s*Exclusive)\D{0,12}([0-9,]+\.[0-9]{2})", text, re.I)
    cur = "SGD" if re.search(r"S\$|SGD", text) else ("USD" if re.search(r"US\$|USD", text) else "CNY")

    def num(s):
        return float(s.replace(",", "")) if s else None

    gross_amt = num(gross.group(1))
    net_amt = num(net.group(1) if net else None)
    tax_amt = num(tax.group(1) if tax else None)
    if tax_amt is None and gross_amt is not None and net_amt is not None and gross_amt >= net_amt:
        tax_amt = round(gross_amt - net_amt, 2)

    # 提取销方、买方与税号
    m_seller = re.search(r"销\s*售\s*方[\s\S]{0,40}?称[：:\s]+([^\s\n\r]+)", text)
    m_seller_id = re.search(r"销\s*售\s*方[\s\S]{0,90}?([0-9A-Z]{15,20})", text)
    m_buyer = re.search(r"购\s*买\s*方[\s\S]{0,40}?称[：:\s]+([^\s\n\r]+)", text)

    seller_name = m_seller.group(1).rstrip("( ") if m_seller else None
    buyer_name = m_buyer.group(1).rstrip("( ") if m_buyer else None

    return {
        "invoice_no": no.group(1),
        "issue_date": f"{date.group(1)}-{int(date.group(2)):02d}-{int(date.group(3)):02d}" if date else None,
        "invoice_type": "数电票（PDF 文本层）" if "数电" in text or "电子发票" in text or "电子 票" in text else
                        ("增值税票（PDF 文本层）" if cur == "CNY" else "Supplier Invoice（PDF 文本层）"),
        "seller_name": seller_name,
        "seller_tax_id": m_seller_id.group(1) if m_seller_id else None,
        "buyer_name": buyer_name,
        "buyer_tax_id": None,
        "net": net_amt,
        "tax": tax_amt,
        "gross": gross_amt,
        "currency": cur,
        "lines": [],
        "xml": None,
        "ns": "pdf_text",
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


# ───────────────────────── OFD 原件解包与结构化直读（FN-2-01） ─────────────────────────

def parse_ofd_content(content: bytes) -> dict | None:
    """OFD 版式发票内置解包直读（工程化接入能力，非 Provider、非自研 OCR）。

    OFD 遵循 GB/T 33190-2016，内部为 zip 容器，包含 OFD.xml、Doc_0 等结构；
    电子发票通常在根目录或 Doc_0 目录下内嵌 XML 发票元数据。
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = z.namelist()
            # 优先寻找内嵌发票业务 XML
            target_xml = None
            for candidate in ("Invoice.xml", "invoice.xml", "EInvoice.xml"):
                for n in names:
                    if n.endswith(candidate):
                        target_xml = z.read(n)
                        break
                if target_xml:
                    break

            if not target_xml:
                # 遍历查找任一含有 Invoice 标识的 xml
                for n in names:
                    if n.lower().endswith(".xml"):
                        c = z.read(n)
                        if b"Invoice" in c or b"GrossAmount" in c or b"NetAmount" in c:
                            target_xml = c
                            break

            if target_xml:
                doc = parse_einvoice_xml(target_xml)
                if doc:
                    doc["ns"] = "ofd_direct"
                    return doc

            # 若未找到独立业务 XML，提取页面内文本流
            texts = []
            for n in names:
                if "content.xml" in n.lower():
                    try:
                        c = z.read(n)
                        root = ET.fromstring(c.decode("utf-8", errors="ignore"))
                        for t in root.iter():
                            if t.text and t.text.strip():
                                texts.append(t.text.strip())
                    except Exception:
                        continue
            if texts:
                full_text = " ".join(texts)
                doc = parse_pdf_fields(full_text)
                if doc:
                    doc["ns"] = "ofd_direct"
                    return doc
    except Exception:
        return None
    return None


# ───────────────────────── 二维码/条码解码直读（FN-2-01） ─────────────────────────

def parse_qrcode_text(qr_text: str) -> dict | None:
    """国税/数电标准二维码字符串结构化直读（非 Provider，平台内置能力）。

    格式常见：
      01,10,发票代码,发票号码,合计金额,开票日期,校验码,...
      01,04,发票代码,发票号码,不含税金额,开票日期,校验码,...
      或数电票直接编码的 JSON / URL。
    """
    if not qr_text or not isinstance(qr_text, str):
        return None
    s = qr_text.strip()
    parts = s.split(",")
    if len(parts) >= 7 and parts[0] in ("01", "02", "03", "04", "10"):
        # 标准国税增值税发票二维码
        code = parts[2].strip()
        no = parts[3].strip()
        amt = _num(parts[4])
        dt_raw = parts[5].strip()
        date_str = None
        if len(dt_raw) == 8 and dt_raw.isdigit():
            date_str = f"{dt_raw[:4]}-{dt_raw[4:6]}-{dt_raw[6:8]}"
        return {
            "invoice_code": code,
            "invoice_no": no,
            "gross": amt,
            "issue_date": date_str,
            "check_code": parts[6].strip() if len(parts) > 6 else None,
            "currency": "CNY",
            "invoice_type": "增值税发票（二维码解码）",
            "source": "qr_code",
            "confidence": 0.99,
        }
    return None

