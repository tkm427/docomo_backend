from chalice import Chalice, BadRequestError, Response, CORSConfig, NotFoundError
import boto3
import uuid
import bcrypt
from boto3.dynamodb.conditions import Attr, Key
from datetime import datetime
import random
import requests
import os
import base64

dynamodb = boto3.resource(
    "dynamodb", region_name="ap-northeast-1",
    endpoint_url="http://localhost:8000"
)
app = Chalice(app_name="docomo_backend")

headers = {'Content-Type': 'application/json'}

users_table = dynamodb.Table("Users")
sessions_table = dynamodb.Table("Sessions")
themes_table = dynamodb.Table("Themes")
feedbacks_table = dynamodb.Table("Feedback")

CLIENT_ID = os.getenv("ZOOM_CLIENT_ID")
CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET")
ACCOUNT_ID = os.getenv("ZOOM_ACCOUNT_ID")

# CORS設定
cors_config = CORSConfig(
    allow_origin='*',
    allow_headers=['Content-Type', 'Authorization'],
    max_age=600,
    expose_headers=['Authorization'], 
    allow_credentials=True
)

def create_zoom_meeting():
    # Zoom API エンドポイント
    zoom_api_url = "https://api.zoom.us/v2/users/me/meetings"
    
    # Zoom API アクセストークン発行
    auth_str = f"{CLIENT_ID}:{CLIENT_SECRET}"
    b64_auth_str = base64.b64encode(auth_str.encode()).decode()
    headers = {
        "Authorization": f"Basic {b64_auth_str}",
    }

    try:
        response = requests.post(
            f"https://zoom.us/oauth/token?grant_type=account_credentials&account_id={ACCOUNT_ID}",
            headers=headers
        )
        access_token = response.json()["access_token"]
    except Exception as e:
        raise BadRequestError(f"Failed to get access token: {e}")
    
    # ミーティング作成のためのデータ
    meeting_details = {
        "topic": "Group Discussion",
        "type": 1,  # Instant meeting
        "settings": {
            "host_video": True,
            "participant_video": True
        }
    }
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    response = requests.post(zoom_api_url, headers=headers, json=meeting_details)
    
    if response.status_code == 201:
        meeting_info = response.json()
        return meeting_info["join_url"]
    else:
        print(f"Error: {response.status_code}")
        print(response.json())
        return None

@app.route("/session", methods=["POST"], cors=cors_config)
def create_or_join_session():
    request_body = app.current_request.json_body
    user_id = request_body.get("userId")

    if not user_id:
        return {"error": "userId is required"}, 400

    # Check for available sessions
    response = sessions_table.scan(FilterExpression=Attr("user_id").size().lt(5))
    available_sessions = response["Items"]

    if not available_sessions:
        # Create a new session
        session_id = str(uuid.uuid4())
        theme = get_random_theme()
        sessions_table.put_item(
            Item={
                "id": session_id,
                "theme_id": theme["id"],
                "user_id": [user_id],  # First user
                "is_end": False,
                "date": datetime.now().isoformat(),
                "zoom_url": "",
            }
        )
        response_body = {
            "sessionId": session_id,
            "userCount": 1,
            "message": "New session created",
            "theme": theme["content"],
        }
        return Response(body=response_body, status_code=201, headers={})
    else:
        # Join existing session
        session = available_sessions[0]
        if user_id in session["user_id"]:
            response_body = {
                "sessionId": session["id"],
                "userCount": len(session["user_id"]),
                "message": "User already in session",
            }
            return Response(body=response_body, status_code=200, headers={})

        session["user_id"].append(user_id)
        user_count = len(session["user_id"])

        update_expression = "SET user_id = :users"
        expression_values = {":users": session["user_id"]}

        if user_count == 5:
            # Create Zoom URL and update session
            zoom_url = create_zoom_meeting()
            update_expression += ", zoom_url = :zoom"
            expression_values[":zoom"] = zoom_url

        sessions_table.update_item(
            Key={"id": session["id"]},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_values,
        )
        response_body = {
            "sessionId": session["id"],
            "userCount": user_count,
            "message": "Joined existing session",
        }
        return Response(body=response_body, status_code=200, headers=headers)


# ユーザー登録
@app.route('/register', methods=['POST'], cors=cors_config)
def register():
    request = app.current_request.json_body
    name = request.get('name')
    email = request.get('email')
    password = request.get('password')

    if not name or not email or not password:
        return Response(
            body={'error': '名前、メールアドレス、パスワードは必須です。'},
            status_code=400,
            headers=headers
        )

    # メールアドレスが既に存在するかチェック
    response = users_table.query(
        IndexName="EmailIndex",  # 作成したGSIの名前を指定
        KeyConditionExpression=Key('email').eq(email)
    )

    # クエリ結果にデータが存在する場合（既にユーザーが登録されている場合）
    if response['Items']:
        return Response(
            body={'error': 'このメールアドレスは既に登録されています。'},
            status_code=400,
            headers=headers
        )

    # パスワードをハッシュ化
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    # IDを生成
    user_id = str(uuid.uuid4())

    # ユーザー情報を保存
    users_table.put_item(
        Item={
            'id': user_id,
            'name': name,
            'email': email,
            'password_hash': password_hash
        }
    )

    return Response(
        body={'message': 'ユーザー登録が完了しました。', 'userId': user_id},
        status_code=201,
        headers=headers
    )

# ユーザーログイン
@app.route('/login', methods=['POST'], cors=cors_config)
def login():
    request = app.current_request.json_body
    email = request.get('email')
    password = request.get('password')

    if not email or not password:
        return Response(
            body={'error': 'メールアドレスとパスワードは必須です。'},
            status_code=400,
            headers=headers
        )

    # メールアドレスでユーザーを検索
    response = users_table.query(
        IndexName="EmailIndex",  # 作成したGSIの名前を指定
        KeyConditionExpression=Key('email').eq(email)  # Keyオブジェクトを使用してクエリを実行
    )

    # クエリ結果からユーザー情報を取得
    user = response['Items'][0] if response['Items'] else None  # ユーザーが存在しない場合はNone


    if not user:
        return Response(
            body={'error': 'メールアドレスまたはパスワードが正しくありません。'},
            status_code=404,
            headers=headers
        )

    # パスワードの確認
    if not bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
        return Response(
            body={'error': 'メールアドレスまたはパスワードが正しくありません。'},
            status_code=400,
            headers=headers
        )

    return Response(
        body={'userId': user['id']},
        status_code=200,
        headers=headers
    )



def get_random_theme():
    response = themes_table.scan()
    themes = response["Items"]
    return random.choice(themes) if themes else None


@app.route("/end_session/{session_id}", methods=["GET"], cors=cors_config)
def end_session():
    session_id = app.current_request.query_params.get("session_id")

    session = sessions_table.get_item(Key={"ID": session_id})["Item"]
    session["is_end"] = True
    sessions_table.put_item(Item=session)
    response_body = {"message": "Session ended"}
    return Response(body=response_body, status_code=200, headers=headers)


@app.route("/add_theme", methods=["POST"], cors=cors_config)
def add_theme():
    request = app.current_request
    data = request.json_body

    table = themes_table
    table.put_item(
        Item={
            "id": data["id"],
            "content": data["content"],
        }
    )


@app.route("/get_zoom_url/{id}", methods=["GET"], cors=cors_config)
def get_zoom_url(id):
    def get_user_name(id):
        table = users_table
        response = table.get_item(Key={"id": id})
        item = response["Item"]
        return item["name"]

    table = sessions_table
    response = table.get_item(Key={"id": id})
    item = response["Item"]
    if ("zoom_url" not in item) or (item["zoom_url"] == ""):
        raise NotFoundError("No Zoom URL")
    else:
        username = [get_user_name(id) for id in item["user_id"]]
        return Response(
            body={
                "zoomUrl": item["zoom_url"],
                "theme": item["theme"],
                "userId": item["user_id"],
                "userName": username,
            },
            status_code=200,
            headers=headers,
        )

@app.route("/feedback", methods=["POST"], cors=cors_config)
def feedback():
    request = app.current_request
    data = request.json_body

    table = feedbacks_table
    for user_id in data.keys():
        feedback_id = str(uuid.uuid4())
        session_date = sessions_table.get_item(Key={"id": data["sessionId"]})["Item"]["date"]
        table.put_item(
            Item={
                "id": feedback_id,
                "session_id": data["sessionId"],
                "user_id": user_id,
                "date": session_date,
                "proactivity": data[user_id]["proactivity"], # 積極性
                "logicality": data[user_id]["logicality"], # 論理的思考
                "leadership": data[user_id]["leadership"], # リーダーシップ
                "cooperation": data[user_id]["cooperation"], # 協力性
                "expression": data[user_id]["expression"], # 発信力
                "consideration": data[user_id]["consideration"], # 気配り
                "comment": data[user_id]["comment"], # コメント
            }
        )
    return Response(body={"message": "Feedback saved"}, status_code=201, headers=headers)

@app.route("/get_feedback/{user_id}", methods=["GET"], cors=cors_config)
def get_feedback(user_id):
    table = feedbacks_table
    response = table.scan(FilterExpression=Attr("user_id").eq(user_id))
    items = response["Items"]
    return Response(body=items, status_code=200, headers=headers)