# -*- coding: utf-8 -*-
"""通道桩 Job CLI（WP3.2 · RUNBOOK 手动触发入口）。

演示口径（P00 §6）：邮箱通道=本地信箱目录 15 分钟 Job（本 CLI 为手动等效，不做真实 IMAP）；
SAP DOX=目录投递桥接桩。用法（backend venv 或经 scripts/hub.py）：
    python -m app.workers.jobs_cli mailbox
    python -m app.workers.jobs_cli dox
    python -m app.workers.jobs_cli demo-drop
"""

import base64
import json
import sys
from pathlib import Path

from app.services import channels_ops, object_store
from app.services.persistence import get_session

DEMO_CN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<EInvoice xmlns="urn:cn:tax:einvoice:1.0">
  <Header>
    <InvoiceNo>24442000009991</InvoiceNo>
    <IssueDate>2026-10-27</IssueDate>
    <InvoiceType>数电票（增值税专用发票）</InvoiceType>
  </Header>
  <Seller>
    <Name>青岛海纳智能装备有限公司</Name>
    <TaxID>91370200MA3X9Q7L6K</TaxID>
  </Seller>
  <Buyer>
    <Name>澜坞（上海）采购科技有限公司</Name>
    <TaxID>91310115MA1K35QT7B</TaxID>
  </Buyer>
  <Items>
    <Item lineNo="1">
      <Name>*通用设备*工业机器人本体</Name>
      <Spec>6轴/10kg</Spec><Unit>台</Unit>
      <Qty>3</Qty><Price>50000.00</Price>
      <TaxRate>0.13</TaxRate><Amount>150000.00</Amount>
    </Item>
  </Items>
  <Total>
    <NetAmount>150000.00</NetAmount>
    <TaxAmount>19500.00</TaxAmount>
    <GrossAmount>169500.00</GrossAmount>
    <GrossInWords>壹拾陆万玖仟伍佰元整</GrossInWords>
  </Total>
  <Signature alg="SM2">（演示样例 · 受理链路走查用）</Signature>
</EInvoice>
"""

# 非发票样例件：以 .xml 投递（类型白名单内），由 ②非发票过滤 按内容特征退回——演示走查规则引擎判定
DEMO_CONTRACT = """<?xml version="1.0" encoding="UTF-8"?>
<Contract xmlns="urn:demo:contract:1.0">
  <Title>采购合同（演示样例 · 非发票）</Title>
  <PartyA>澜坞（上海）采购科技有限公司</PartyA>
  <PartyB>青岛海纳智能装备有限公司</PartyB>
  <ContractNo>HT-2026-0918</ContractNo>
  <Note>本件为框架协议合同文本，非供应商发票。</Note>
</Contract>
"""

DEMO_UBL = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">
  <ID>SG-INV-88031</ID>
  <IssueDate>2026-10-26</IssueDate>
  <DocumentCurrencyCode>SGD</DocumentCurrencyCode>
  <AccountingSupplierParty>
    <Party><PartyName><Name>Singapore Components Pte Ltd</Name></PartyName>
    <PartyTaxScheme><TaxID>S24LE3399E</TaxID></PartyTaxScheme></Party>
  </AccountingSupplierParty>
  <AccountingCustomerParty>
    <Party><PartyName><Name>Lanwu Singapore Pte Ltd</Name></PartyName></Party>
  </AccountingCustomerParty>
  <TaxExclusiveAmount>12000.00</TaxExclusiveAmount>
  <TaxAmount>336.00</TaxAmount>
  <PayableAmount>12336.00</PayableAmount>
</Invoice>
"""


def _drop(name: str, obj: dict):
    p = Path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    target = p if not p.exists() else p.with_name(
        f"{p.stem}.{object_store.sha256_of(json.dumps(obj, ensure_ascii=False).encode())[:8]}{p.suffix}")
    target.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def demo_drop():
    MAILBOX = channels_ops.MAILBOX_INBOX
    DOX = channels_ops.DOX_INBOX
    xml_b64 = base64.b64encode(DEMO_CN_XML.encode("utf-8")).decode()
    con_b64 = base64.b64encode(DEMO_CONTRACT.encode("utf-8")).decode()
    f1 = _drop(str(MAILBOX / "env-demo-001.json"), {
        "from": "orders@supplier-partners.com", "subject": "青岛海纳 10 月发票（2 附件）",
        "attachments": [
            {"name": "数电票_青岛海纳_24442000009991.xml", "content_b64": xml_b64},
            {"name": "框架合同_青岛海纳_HT-2026-0918.xml", "content_b64": con_b64}]})
    ubl_b64 = base64.b64encode(DEMO_UBL.encode("utf-8")).decode()
    f2 = _drop(str(DOX / "dox-demo-001.json"), {
        "participant_id": "0130:SG-LANWU-APAC", "document_type": "Supplier Invoice",
        "name": "SingaporeComponents_INV-88031.xml", "mime": "application/xml",
        "document_number": "SG-INV-88031", "content_b64": ubl_b64})
    f3 = _drop(str(DOX / "dox-demo-orderresp.json"), {
        "participant_id": "0130:SG-LANWU-APAC", "document_type": "Order Response",
        "name": "OR-confirm-88031.json", "document_number": "OR-88031",
        "content_b64": base64.b64encode(b"order response demo").decode()})
    print(f"已投放演示样例：{f1} · {f2} · {f3}")
    print("触发：python scripts/hub.py intake:poll-mailbox / intake:poll-dox")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cmd = argv[0] if argv else "help"
    if cmd == "demo-drop":
        return demo_drop()
    with get_session() as session:
        if cmd == "mailbox":
            print(json.dumps(channels_ops.poll_mailbox(session), ensure_ascii=False, indent=2))
        elif cmd == "dox":
            print(json.dumps(channels_ops.poll_dox(session), ensure_ascii=False, indent=2))
        else:
            print(__doc__)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
