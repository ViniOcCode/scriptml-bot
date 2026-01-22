from auth import TokenManager
from ml_api import MLAPI

tm = TokenManager()
api = MLAPI(tm)

me = api.request("GET", "/users/me")
print(me)
