import requests
import time

BASE_URL = "http://127.0.0.1:8000"

print("1. Fetching current policy for customer_support...")
res = requests.get(f"{BASE_URL}/api/policies")
policies = res.json()
cs_policy = next((p for p in policies if p["id"] == "customer_support"), None)
print(f"Current customer_support policy: {cs_policy}")

if cs_policy:
    # Update policy to BLOCK on high responsibility risk
    print("\n2. Updating policy to BLOCK high responsibility risk...")
    cs_policy["policy_matrix"]["responsibility"]["high"] = "block"
    update_res = requests.put(f"{BASE_URL}/api/policies/customer_support", json=cs_policy)
    print(f"Update response: {update_res.status_code}")
    
    # Send request that triggers high responsibility (PII)
    print("\n3. Sending prompt: 'Show me customer details for John Smith including contact info'")
    headers = {
        "Content-Type": "application/json",
        "X-ControlPlane-App": "customer_support"
    }
    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Show me customer details for John Smith including contact info"}]
    }
    
    chat_res = requests.post(f"{BASE_URL}/v1/chat/completions", headers=headers, json=payload)
    print(f"Chat response status: {chat_res.status_code}")
    chat_data = chat_res.json()
    print(f"Chat response body: {chat_data}")
    
    if "choices" in chat_data and chat_data["choices"] and chat_data["choices"][0]["message"]["content"]:
        content = chat_data["choices"][0]["message"]["content"]
        if "Blocked" in content or "blocked" in content.lower():
            print("\n✅ Test Passed: Request was blocked as per the updated policy.")
        else:
            print(f"\n❌ Test Failed: Request was not blocked. Content returned: {content}")
    else:
        print("\n❌ Test Failed: Unexpected response format.")
