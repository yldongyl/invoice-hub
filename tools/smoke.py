#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""invoice-hub 冒烟检查（P07 1.4 · 对运行中实例脚本化验证，逐项 PASS/FAIL）。

前置：`make run` / `python scripts/hub.py run`（默认 http://127.0.0.1:8000）且已 `make seed`。
退出码：全 PASS=0；任一 FAIL=1（FAIL 行附明确错误信息）。

十步（P07 1.4 规定顺序）：
  01 healthz            GET /healthz status=ok
  02 seed 装载断言       11 案件在库（CN 7 + OS 4，经列表 API）
  03 dashboard 聚合      双实例各一次：KPI 数值非空 + 红线对照布尔 + Top5=5 行
  04 case-detail 三案    view=full 聚合过 invoice-case.schema（jsonschema 缺失时降级结构断言并注明）
  05 证据查询            0387 total.gross_amount：七要素齐备（FN-3-02 口径，缺项即黑盒）
  06 时间线查询          0387 全事件 act ∈ enum-registry.timeline_event
  07 审计链完整性        verify_chain 三链域全绿（CN/OS/PLATFORM）
  08 受控写拒绝路径      无有效凭据的 release → 4xx 且错误码 ∈ 受控拒绝词汇（五要素守门生效）
  09 web 静态可达        根路径 307→/web/dashboard-overview.html 200；共享 js 200
  10 demo-mode 探测      /web/js/demo-mode.js 在位且含 healthz 探测+「演示模式（未连接后台）」角标口径
                         （P07 允许 HTTP 直查 + js 逻辑说明；独立演示态=file:// 双击打开，RUNBOOK §3）
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONTRACTS = ROOT / "contracts"
SEEDS = ROOT / "seeds"

RESULTS = []


def record(step, name, ok, msg=""):
    RESULTS.append((step, name, ok, msg))
    print(f"  {'PASS' if ok else 'FAIL'}  {step} · {name}" + (f" —— {msg}" if (msg and not ok) else ""))
    return ok


def http_json(base, path, method="GET", body=None, timeout=15, headers=None):
    url = base + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req_headers = dict(headers or {})
    if data:
        req_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:
        return None, str(e)


def _case_schema_validator():
    """镜像 tests/conftest.py 口径：同目录相对 $ref 改写 file URI + referencing Registry
    （invoice-case→events 等跨文件引用可解析）。jsonschema 缺失时返回 None（降级结构断言）。"""
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
    except ImportError:
        return None

    def to_uri(n):
        p = str(CONTRACTS / n).replace("\\", "/").lstrip("/")
        return "file:///" + quote(p, safe="/:")

    def absolutize(node):
        if isinstance(node, dict):
            return {k: (to_uri(v) if (k == "$ref" and isinstance(v, str)
                                      and re.fullmatch(r"[\w.-]+\.json\Z", v))
                        else absolutize(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [absolutize(x) for x in node]
        return node

    loaded = []
    for n in ("invoice-schema.json", "invoice-case.schema.json", "events.schema.json",
              "provider-spi.schema.json", "routing-config.schema.json", "adapter-contract.schema.json"):
        s = absolutize(json.loads((CONTRACTS / n).read_text(encoding="utf-8")))
        Draft202012Validator.check_schema(s)
        loaded.append((to_uri(n), s))
    reg = Registry().with_resources([(u, Resource.from_contents(s)) for u, s in loaded])
    return Draft202012Validator(dict(loaded)[to_uri("invoice-case.schema.json")], registry=reg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    print(f"invoice-hub 冒烟检查 @ {base}")
    fails = 0

    auth_headers = {}
    code_mfa, mfa = http_json(base, "/api/platform/auth/mfa/challenge", "POST", {
        "username": "王莉",
        "tenant_id": "TENANT-CN-LANWU-001",
    })
    code, login = http_json(base, "/api/platform/auth/login", "POST", {
        "username": "王莉",
        "password": "demo-password",
        "tenant_id": "TENANT-CN-LANWU-001",
        "mfa_challenge_id": mfa.get("challenge_id") if isinstance(mfa, dict) else None,
        "mfa_code": mfa.get("dev_code") if isinstance(mfa, dict) else None,
        "remember_device": True,
    })
    if code == 200 and isinstance(login, dict) and login.get("session_token"):
        auth_headers = {"Authorization": "Bearer " + login["session_token"]}

    # 01 healthz
    code, h = http_json(base, "/healthz")
    fails += not record("01", "healthz", code == 200 and isinstance(h, dict) and h.get("status") == "ok",
                        f"status={code} body={str(h)[:120]}")

    # 02 seed 装载断言（11 案件：CN 7 + OS 4）
    c1, cn = http_json(base, "/v1/cases?instance=CN", headers=auth_headers)
    c2, os_ = http_json(base, "/v1/cases?instance=OS", headers=auth_headers)
    ok = c1 == 200 and c2 == 200 and cn.get("total") == 7 and os_.get("total") == 4
    fails += not record("02", "seed 装载断言（11 案件在库）", ok,
                        f"CN total={cn.get('total') if isinstance(cn, dict) else cn} OS total={os_.get('total') if isinstance(os_, dict) else os_}")

    # 03 dashboard 双实例
    b1, d1 = http_json(base, "/v1/dashboard?instance=cn", headers=auth_headers)
    b2, d2 = http_json(base, "/v1/dashboard?instance=os", headers=auth_headers)
    ok = (b1 == 200 and b2 == 200
          and d1["kpi"]["total"] and d2["kpi"]["total"]
          and isinstance(d1["kpi"]["false_auto"]["within_redline"], bool)
          and len(d1["top_cases"]) == 5 and len(d2["top_cases"]) == 5
          and d1["reconciliation"]["mismatches_unregistered"] == []
          and len(d1["alerts"]) == 3 and len(d1["adapter_status"]["items"]) == 5)
    fails += not record("03", "dashboard 聚合（双实例 KPI 非空/红线布尔/Top5/告警×3/适配×5）", ok,
                        str(d1)[:160] if not ok else "")

    # 04 case-detail 三案聚合过 Schema（jsonschema 缺失降级结构断言）
    full_ids = [("INV-CN-2026-0387", "CN"), ("INV-CN-2026-0379", "CN"), ("INV-SG-2026-0125", "OS")]
    try:
        schema = _case_schema_validator()  # dev 组依赖；干净核心环境缺失时降级
    except Exception as e:
        schema = None
        print(f"        ℹ Schema 校验器构建失败（降级结构断言）：{e}")
    bad = []
    for cid, inst in full_ids:
        code, agg = http_json(base, f"/v1/cases/{cid}?view=full&instance={inst}", headers=auth_headers)
        if code != 200:
            bad.append(f"{cid} HTTP {code}")
            continue
        if schema is not None:
            errs = list(schema.iter_errors(agg))
            if errs:
                bad.append(f"{cid}: {errs[0].message[:80]}")
        else:  # 降级：契约必填键 + full allOf 条件断言（stdlib 结构校验）
            need = {"caseId", "status", "detail_level", "meta", "facts",
                    "checks", "evidence", "timeline", "links", "items", "file", "nextAction"}
            if agg.get("detail_level") == "full" and not need <= set(agg):
                bad.append(f"{cid} 缺键 {sorted(need - set(agg))}")
    note = "" if schema else "jsonschema 未安装，降级为结构断言（pip install -r requirements-dev.txt 启用全量 Schema 校验）"
    fails += not record("04", "case-detail 三案聚合 Schema 校验", not bad, ("; ".join(bad) + " " + note).strip())
    if schema is None and not bad:
        print(f"        ℹ {note}")

    # 05 证据查询（七要素 = FN-3-02 验收口径）
    code, ev = http_json(base, "/v1/cases/INV-CN-2026-0387/evidence?field=total.gross_amount&instance=CN", headers=auth_headers)
    ok = code == 200 and ev.get("total", 0) >= 1
    if ok:
        e = ev["items"][0]
        seven = (("field" in e) and ("value" in e) and ("source" in e) and ("confidence" in e)
                 and all(k in e.get("evidence", {}) for k in ("page", "bbox", "raw_text", "rule", "model_version", "provider")))
        ok = seven
    fails += not record("05", "证据查询 0387 total.gross_amount 七要素齐备", ok, str(ev)[:160] if not ok else "")

    # 06 时间线事件码 ∈ registry
    reg = json.loads((CONTRACTS / "enum-registry.json").read_text(encoding="utf-8"))
    act_vocab = {v["code"] for v in reg["categories"]["timeline_event"]["values"]}
    code, tl = http_json(base, "/v1/cases/INV-CN-2026-0387/timeline?instance=CN", headers=auth_headers)
    ok = code == 200 and tl.get("total") == 11 and all(t["act"] in act_vocab for t in tl.get("items", []))
    fails += not record("06", "时间线查询（11 事件·事件码 ∈ enum-registry）", ok, str(tl)[:160] if not ok else "")

    # 07 审计链完整性（读取服务与后端默认库——runtime/invoice_hub.db）
    ok = True; msg = ""
    try:
        sys.path.insert(0, str(ROOT / "backend"))
        from sqlalchemy.orm import sessionmaker
        from app.services import persistence
        from app.services.audit_chain import verify_chain
        eng = persistence.get_engine()  # 默认 URL=runtime/invoice_hub.db（与 server 同库；仅追加 VerifyRun 登记）
        s = sessionmaker(bind=eng, expire_on_commit=False)()
        res = verify_chain(s, verifier="smoke")
        ok = bool(res.get("ok"))
        s.close()
        msg = "" if ok else f"断点 blk#{res.get('bad_blk')} 域 {res.get('scope')} {res.get('detail')}"
    except Exception as e:
        ok = False; msg = f"链校验执行异常: {e}"
    fails += not record("07", "审计链完整性校验（CN/OS/PLATFORM 三域）", ok, msg)

    # 08 受控写拒绝路径（缺有效凭据的 release → 受控框架拒绝）
    code, rej = http_json(base, "/v1/cases/INV-CN-2026-0379/actions/release", "POST",
                          {"actor": "王莉", "instance": "CN", "token": "smoke-invalid-token",
                           "self_confirmed": True}, headers=auth_headers)
    ec = rej.get("detail", {}).get("error_code") if isinstance(rej, dict) else None
    ok = code in (400, 401, 403, 409, 422, 428) and ec in ("E_CONFIRM_INVALID", "E_RISK_NOT_SHOWN",
                                                            "E_PERM_DENIED", "E_SELF_CONFIRM_REQUIRED",
                                                            "E_STATE_PRECONDITION")
    fails += not record("08", "受控写拒绝路径（无有效凭据 release 被拒·五要素守门）", ok,
                        f"status={code} error_code={ec}")

    # 09 web 首页与本地静态资源可达（Tailwind 已本地构建，禁止运行时依赖 CDN）
    code, _ = http_json(base, "/")
    ok9a = code == 200  # urllib 默认跟随 307 → 200
    code2, _ = http_json(base, "/web/js/api-client.js")
    code_guard, guard = http_json(base, "/web/js/auth-guard.js")
    code3, css = http_json(base, "/web/css/invoice-hub.css")
    ok_guard = code_guard == 200 and isinstance(guard, str) and "/api/platform/auth/session" in guard
    ok_css = code3 == 200 and isinstance(css, str) and ".bg-surface" in css and ".rounded-card" in css
    fails += not record("09", "web 首页（307→login 200）与本地 js/css 可达", ok9a and code2 == 200 and ok_guard and ok_css,
                        f"root={code} api-client.js={code2} auth-guard.js={code_guard} invoice-hub.css={code3}")

    # 10 demo-mode 探测（HTTP 直查 js 逻辑；独立演示态见 RUNBOOK §3）+ 本地 CSS 引用纪律
    code, dm = http_json(base, "/web/js/demo-mode.js")
    ok = (code == 200 and isinstance(dm, str) and "/healthz" in dm
          and "演示模式（未连接后台）" in dm)
    if ok:
        for page in ("/web/dashboard-overview.html", "/web/case-detail.html"):
            pc, ph = http_json(base, page)
            ok = (ok and pc == 200 and "js/auth-guard.js" in ph and "js/demo-mode.js" in ph
                  and 'href="css/invoice-hub.css"' in ph
                  and "cdn.tailwindcss.com" not in ph
                  and "fonts.googleapis.com" not in ph)
    fails += not record("10", "demo-mode 回退在位 + 登录守卫 + 本地 CSS 引用（无 CDN 依赖）", ok,
                        "auth-guard.js、demo-mode.js、本地 CSS 引用缺失，或页面仍引用外部 CDN" if not ok else "")

    print("-" * 70)
    print(f"冒烟结果：{len(RESULTS) - len([r for r in RESULTS if not r[2]])}/{len(RESULTS)} PASS")
    if any(not r[2] for r in RESULTS):
        print("存在 FAIL——错误信息见上行；修复指引见 docs/RUNBOOK.md §8 故障排查")
        return 1
    print("全部 PASS —— 运行基线可用（独立演示形态：file:// 直接打开 web/*.html，见 RUNBOOK §3）")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
