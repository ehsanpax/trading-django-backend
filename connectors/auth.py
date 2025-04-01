# auth.py example usage:
from ctrader_open_api.endpoints import EndPoints
from auth import Auth

auth = Auth(appClientId='13641_QqAQIxv5R7wUGHoSjbKTalzNMPbyDEt6b9I8VxgwUO3rs3qN0P', appClientSecret='tFzXEFQi2fYtaIWm7xdz54n6jhnT5dQHGT82Jf5Z3J6DSUwV1i', redirectUri='http://localhost:8000/http://localhost:8000')

# Step 1: Generate authentication URL
print(auth.getAuthUri())

# Step 2: Exchange auth code for a token after user login
token_response = auth.getToken(authCode='received-auth-code')
print(token_response['access_token'])
