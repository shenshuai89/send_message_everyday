#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import datetime
import os
import sys

# === 从环境变量读取配置 ===
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")
BITABLE_APP_TOKEN = os.getenv("BITABLE_APP_TOKEN")
TABLE_ID = os.getenv("TABLE_ID")
WECHAT_WEBHOOK_URL = os.getenv("WECHAT_WEBHOOK_URL")

if not all([FEISHU_APP_ID, FEISHU_APP_SECRET, BITABLE_APP_TOKEN, TABLE_ID, WECHAT_WEBHOOK_URL]):
    print("❌ 缺少必要环境变量，请检查 GitHub Secrets 设置。", file=sys.stderr)
    print(f"App ID : {FEISHU_APP_ID}") 
    print(f"App SECRET : {FEISHU_APP_SECRET}") 
    print(f"App ID 长度: {len(FEISHU_APP_ID)}") 
    print(f"App Secret 镇长度: {len(FEISHU_APP_SECRET)}")
    sys.exit(1)
else:
    print("✅ 环境变量已加载：")
    print(f"   FEISHU_APP_ID 长度: {len(FEISHU_APP_ID)}")
    print(f"   FEISHU_APP_SECRET 长度: {len(FEISHU_APP_SECRET)} (值已隐藏)")
    print(f"   BITABLE_APP_TOKEN: {BITABLE_APP_TOKEN}")
    print(f"   TABLE_ID: {TABLE_ID}")
    print(f"   WECHAT_WEBHOOK_URL 长度: {len(WECHAT_WEBHOOK_URL)} (值已隐藏)")
    
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

    target_date = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
    due_soon = []

    for rec in records:
        fields = rec["fields"]
        # ⚠️ 请根据你的飞书表格字段名修改以下键名！
        deadline = fields.get("Deadline")  # 示例字段名，必须与你表格中的字段标识符一致
        contract_name = fields.get("ContractName", "未命名合同")
        owner = fields.get("Owner", "未知负责人")

        # 飞书日期字段返回格式为 "YYYY-MM-DD"
        if isinstance(deadline, str) and deadline == target_date:
            due_soon.append({
                "name": contract_name,
                "owner": owner,
                "date": deadline
            })

    if not due_soon:
        print("✅ 今日无即将到期的合同（7天内）")
        return

    # 构造企业微信消息
    content = "【合同到期提醒】以下合同将在7天后到期，请及时处理：\n\n"
    for item in due_soon:
        content += f"📄 合同名称：{item['name']}\n"
        content += f"👤 负责人：{item['owner']}\n"
        content += f"🗓 截止日期：{item['date']}\n"
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
