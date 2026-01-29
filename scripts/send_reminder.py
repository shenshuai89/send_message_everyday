import requests
import datetime
import os
import json
import sys

# === 从环境变量读取配置 ===
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")
BITABLE_APP_TOKEN = os.getenv("BITABLE_APP_TOKEN")
TABLE_ID = os.getenv("TABLE_ID")
WECHAT_WEBHOOK_URL = os.getenv("WECHAT_WEBHOOK_URL")

if not all([FEISHU_APP_ID, FEISHU_APP_SECRET, BITABLE_APP_TOKEN, TABLE_ID, WECHAT_WEBHOOK_URL]):
    print("❌ 缺少必要环境变量，请检查 GitHub Secrets 设置。")
    sys.exit(1)

# === 获取飞书 tenant_access_token ===
def get_tenant_access_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
    resp = requests.post(url, json=payload)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"获取飞书 token 失败: {data}")
    return data["tenant_access_token"]

# === 获取所有记录（支持分页）===
def fetch_bitable_records(token):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{TABLE_ID}/records"
    headers = {"Authorization": f"Bearer {token}"}
    records = []
    page_token = None
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(url, headers=headers, params=params)
        data = resp.json()
        if data.get("code") != 0:
            raise Exception(f"获取飞表数据失败: {data}")
        items = data["data"]["items"]
        records.extend(items)
        if not data["data"].get("has_more"):
            break
        page_token = data["data"]["page_token"]
    return records

# 从飞书富文本字段值中提取纯文本
def extract_rich_text(field_value):
    """
    从飞书富文本字段值中提取纯文本。
    支持：
      - None / 空值
      - 字符串（兼容普通文本字段）
      - 富文本列表 [{"text": "..."}, ...]
    """
    if not field_value:
        return ""
    if isinstance(field_value, str):
        return field_value
    if isinstance(field_value, list):
        return "".join(item.get("text", "") for item in field_value if isinstance(item, dict))
    return str(field_value)

# === 主逻辑 ===
def main():
    token = get_tenant_access_token()
    records = fetch_bitable_records(token)

    today = datetime.date.today()
    due_soon = []

    for rec in records:
        fields = rec["fields"]
        
        # --- 解析 ContractName ---
        contract_name_raw = fields.get("ContractName")
        if isinstance(contract_name_raw, list) and len(contract_name_raw) > 0:
            contract_name = contract_name_raw[0].get("text", "未命名合同")
        else:
            contract_name = "未命名合同"

        # --- 解析 Owner ---
        owner_raw = fields.get("Owner")
        if isinstance(owner_raw, list) and len(owner_raw) > 0:
            owner = owner_raw[0].get("text", "未知负责人")
        else:
            owner = "未知负责人"

        # --- 解析 Deadline（关键修改点）---
        deadline_value = fields.get("Deadline")
        if not isinstance(deadline_value, (int, float)):
            # 不是数字，跳过（可能是空值或格式错误）
            continue

        try:
            # 飞书时间戳是毫秒，需除以 1000 转为秒
            deadline_date = datetime.datetime.fromtimestamp(
                deadline_value / 1000, tz=datetime.timezone.utc
            ).date()
        except (ValueError, OSError):
            # 时间戳无效（如过大/过小）
            continue

        # 计算剩余天数
        delta = (deadline_date - today).days

        # 提醒：未来 7 天内到期（含今天）
        if 0 <= delta <= 7:
            due_soon.append({
                "name": contract_name,
                "owner": owner,
                "date": deadline_date.isoformat(),
                "days_left": delta
            })

    if not due_soon:
        print("✅ 未来7天内无合同到期（含今天）")
        return

    # 构造企业微信消息
    content = "【合同到期提醒】以下合同将在7天内到期，请及时处理：\n\n"
    for item in due_soon:
        if item["days_left"] == 0:
            suffix = "（今天到期！）"
        elif item["days_left"] == 1:
            suffix = "（明天到期！）"
        else:
            suffix = f"（{item['days_left']}天后到期）"
        content += f"📄 合同名称：{item['name']}\n"
        content += f"👤 负责人：{item['owner']}\n"
        content += f"🗓 截止日期：{item['date']} {suffix}\n"
        content += "------------------------\n"

    msg = {
        "msgtype": "text",
        "text": {
            "content": content.strip()
        }
    }

    # 发送至企业微信
    resp = requests.post(WECHAT_WEBHOOK_URL, json=msg)
    result = resp.json()
    if result.get("errcode") == 0:
        print("✅ 提醒消息已成功发送至企业微信")
    else:
        print(f"❌ 发送失败: {result}", file=sys.stderr)
        sys.exit(1)
