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

# === 主逻辑 ===
def main():
    token = get_tenant_access_token()
    records = fetch_bitable_records(token)

    today = datetime.date.today()
    due_soon = []

    for rec in records:
        fields = rec["fields"]
        # ⚠️ 请根据你的飞书表格字段名修改以下键名！
        deadline_str = fields.get("Deadline")  # 示例字段名
        contract_name = fields.get("ContractName", "未命名合同")
        owner = fields.get("Owner", "未知负责人")

        # 只处理字符串格式的日期
        if not isinstance(deadline_str, str):
            continue

        try:
            deadline = datetime.datetime.strptime(deadline_str, "%Y-%m-%d").date()
        except ValueError:
            # 日期格式无效，跳过
            continue

        # 计算剩余天数（可以是负数，表示已过期）
        delta = (deadline - today).days

        # 提醒：未来 7 天内到期（含今天），即 0 <= delta <= 7
        if 0 <= delta <= 7:
            due_soon.append({
                "name": contract_name,
                "owner": owner,
                "date": deadline_str,
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

if __name__ == "__main__":
    main()
