import requests, json
res = requests.post(
    'https://kapi.kakao.com/v2/api/talk/memo/default/send',
    headers={'Authorization': 'Bearer GFfwyYROCeDCvWThnm6yWppWdsU-xFcDAAAAAQoNGZAAAAGcflvoV0PPWzORmYVE'},
    data={'template_object': json.dumps({"object_type": "text", "text": "MDD봇 테스트!", "link": {}})}
)
print(res.json())
