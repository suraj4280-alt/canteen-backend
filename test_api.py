import urllib.request
import urllib.error
import json
import subprocess
import time

def test_routes():
    server_process = subprocess.Popen([".\\venv\\Scripts\\python.exe", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"])
    time.sleep(3)
    
    try:
        def make_request(url, method="GET", data=None, headers=None):
            req_headers = {"Content-Type": "application/json"}
            if headers: req_headers.update(headers)
            body = json.dumps(data).encode("utf-8") if data else None
            req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
            try:
                with urllib.request.urlopen(req) as response:
                    return response.getcode(), response.read().decode("utf-8")
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode("utf-8")
            except Exception as e:
                return 0, str(e)
                
        print("Testing /api/auth/register ...")
        status, text = make_request("http://127.0.0.1:8000/api/auth/register", method="POST", data={
            "first_name": "Test", "last_name": "User", "email": "test2@tnu.in",
            "uid": "TNU2024009100001", "hostel": "H5", "password": "Password123!"
        })
        print("Register Status:", status, text)
        
        print("\nTesting /api/auth/login ...")
        status, text = make_request("http://127.0.0.1:8000/api/auth/login", method="POST", data={
            "identifier": "TNU2024009100001", "password": "Password123!"
        })
        print("Login Status:", status, text)

        if status == 200:
            token = json.loads(text).get("access_token")
            print("\nTesting /api/auth/me ...")
            status, text = make_request("http://127.0.0.1:8000/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            print("Me Status:", status, text)
            
            print("\nTesting /api/meals/menu ...")
            status, text = make_request("http://127.0.0.1:8000/api/meals/menu?date=2024-10-10&slot_id=1", headers={"Authorization": f"Bearer {token}"})
            print("Menu Status:", status, text)
    finally:
        server_process.terminate()

if __name__ == "__main__":
    test_routes()
