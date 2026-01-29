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

# === 从知识库节点获取 obj_token（作为 APP_TOKEN）===
def get_app_token_from_wiki_node(tenant_access_token):
    """
    调用飞书 /wiki/v2/spaces/get_node 接口，获取节点的 obj_token。
    
    注意：
      - 此 obj_token 是该 wiki 节点（文档/文件夹）的 token，格式如 doc_xxx、box_xxx
      - 它 **不是** 多维表格的 app_token（app_xxx），除非该节点本身是一个多维表格（极少见）
    
    参数:
      tenant_access_token: 有效的飞书 tenant_access_token
      wiki_token: 知识库节点的 token（即 URL 中的 token 参数，如 Bxg8w1ZyFiumEykOE2tcnWgfn9c）
    
    返回:
      obj_token: 节点的对象 token（字符串）
    """
    url = "https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node"
    params = {
        "obj_type": "wiki",
        "token": BITABLE_APP_TOKEN
    }
    headers = {
        "Authorization": f"Bearer {tenant_access_token}"
    }
    resp = requests.get(url, headers=headers, params=params)
    data = resp.json()
    
    if data.get("code") != 0:
        raise Exception(f"获取 wiki 节点失败: {data}")
    
    obj_token = data["data"]["node"]["obj_token"]
    return obj_token

# === 获取所有记录（支持分页）===
def fetch_bitable_records(token, appToken):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{appToken}/tables/{TABLE_ID}/records"
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
    appToken = get_app_token_from_wiki_node(token)
    records = fetch_bitable_records(token, appToken)

    today = datetime.date.today()
    due_soon = []

    for rec in records:
        fields = rec["fields"]
        
        # --- 正确解析富文本字段 ---
        contract_name = extract_rich_text(fields.get("ContractName")) or "未命名合同"
        owner = extract_rich_text(fields.get("Owner")) or "未知负责人"

        # --- 解析 Deadline（毫秒时间戳）---
        deadline_value = fields.get("Deadline")
        if not isinstance(deadline_value, (int, float)):
            continue

        try:
            deadline_date = datetime.datetime.fromtimestamp(
                deadline_value / 1000, tz=datetime.timezone.utc
            ).date()
        except (ValueError, OSError):
            continue

        delta = (deadline_date - today).days
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

    resp = requests.post(WECHAT_WEBHOOK_URL, json=msg)
    result = resp.json()
    if result.get("errcode") == 0:
        print("✅ 提醒消息已成功发送至企业微信")
    else:
        print(f"❌ 发送失败: {result}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
