import requests
res = requests.post("https://kauth.kakao.com/oauth/token", data={"grant_type":"authorization_code","client_id":"d0eb21ff2a868efe8d8cc4b2f2c8d0e3","redirect_uri":"https://example.com","code":"APnsAbLwphLIasMbILw44_9aWwsnBjBNHXhRmo62qGzydMUY5WmMiAAAAAQKFyIgAAABnH5VIwzRDLJpR7eCqA"})

