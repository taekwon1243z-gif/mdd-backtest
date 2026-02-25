import requests
res = requests.post('https://kauth.kakao.com/oauth/token', data={
    'grant_type': 'authorization_code',
    'client_id': 'd0eb21ff2a868efe8d8cc4b2f2c8d0e3',
    'client_secret': 'lvkuIZvwFrgzUV1wzIt8PsU7rTB4FEgW',
    'redirect_uri': 'https://example.com',
    'code': 'VAOR3xdEDePT0tLOgy3HQf1V8arRjZD3fn5qs8hMBFpmyo3BjrllkwAAAAQKDSBaAAABnH5blwAWphHJzwXJqw'
})
print(res.json())
