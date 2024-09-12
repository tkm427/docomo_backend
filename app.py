from chalice import Chalice, BadRequestError, Response, CORSConfig, NotFoundError
import boto3
import uuid
import bcrypt
from boto3.dynamodb.conditions import Attr
import datetime
import random

dynamodb = boto3.resource(
    "dynamodb", region_name="ap-northeast-1",
    endpoint_url="http://localhost:8000"
)
app = Chalice(app_name="docomo_backend")

headers = {'Content-Type': 'application/json'}

users_table = dynamodb.Table("Users")
sessions_table = dynamodb.Table("Sessions")
themes_table = dynamodb.Table("Themes")

# CORS設定
cors_config = CORSConfig(
    allow_origin='*',
    allow_headers=['Content-Type', 'Authorization'],
    max_age=600,
    expose_headers=['Authorization'], 
    allow_credentials=True
)

@app.route("/session", methods=["POST"], cors=cors_config)
def create_or_join_session():
    request_body = app.current_request.json_body
    user_id = request_body.get("userId")

    if not user_id:
        return {"error": "userId is required"}, 400

    # Check for available sessions
    response = sessions_table.scan(FilterExpression=Attr("USERID").size().lt(5))
    available_sessions = response["Items"]

    if not available_sessions:
        # Create a new session
        session_id = str(uuid.uuid4())
        theme = get_random_theme()
        sessions_table.put_item(
            Item={
                "ID": session_id,
                "THEMEID": theme["ID"],
                "USERID": [user_id],  # First user
                "ISEND": False,
                "作成日": datetime.now().isoformat(),
                "ZOOMURL": "",
            }
        )
        response_body = {
            "sessionId": session_id,
            "userCount": 1,
            "message": "New session created",
            "theme": theme["CONTENT"],
        }
        return Response(body=response_body, status_code=201, headers={})
    else:
        # Join existing session
        session = available_sessions[0]
        if user_id in session["USERID"]:
            response_body = {
                "sessionId": session["ID"],
                "userCount": len(session["USERID"]),
                "message": "User already in session",
            }
            return Response(body=response_body, status_code=200, headers={})

        session["USERID"].append(user_id)
        user_count = len(session["USERID"])

        update_expression = "SET USERID = :users"
        expression_values = {":users": session["USERID"]}

        if user_count == 5:
            # Create Zoom URL and update session
            zoom_url = "test_zoom_url"
            update_expression += ", ZOOMURL = :zoom"
            expression_values[":zoom"] = zoom_url

        sessions_table.update_item(
            Key={"ID": session["ID"]},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_values,
        )
        response_body = {
            "sessionId": session["ID"],
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
    existing_user = users_table.get_item(Key={'email': email})
    if 'Item' in existing_user:
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
        body={'message': 'ユーザー登録が完了しました。', 'user_id': user_id},
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
    response = users_table.get_item(Key={'email': email})
    user = response.get('Item')

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
        body={'user_id': user['id']},
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
    session["ISEND"] = True
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
            "ID": data["id"],
            "CONTENT": data["content"],
        }
    )


@app.route("/get_zoom_url/{id}", methods=["GET"], cors=cors_config)
def get_zoom_url(id):
    def get_user_name(id):
        table = users_table
        response = table.get_item(Key={"ID": id})
        item = response["Item"]
        return item["NAME"]

    table = sessions_table
    response = table.get_item(Key={"ID": id})
    item = response["Item"]
    if ("ZOOMURL" not in item) or (item["ZOOMURL"] == ""):
        raise NotFoundError("No Zoom URL")
    else:
        username = [get_user_name(id) for id in item["USERID"]]
        return Response(
            body={
                "zoomUrl": item["ZOOMURL"],
                "thema": item["THEMA"],
                "userId": item["USERID"],
                "userName": username,
            },
            status_code=200,
            headers=headers,
        )
