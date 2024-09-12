from chalice import Chalice, BadRequestError, Response, CORSConfig
import boto3
import uuid
import bcrypt

app = Chalice(app_name='docomo_backend')


dynamodb = boto3.resource('dynamodb', region_name='ap-northeast-1', endpoint_url='http://localhost:8000')

# CORS設定
cors_config = CORSConfig(
    allow_origin='*',
    allow_headers=['Content-Type', 'Authorization'],
    max_age=600,
    expose_headers=['Authorization'], 
    allow_credentials=True
)

users_table = dynamodb.Table('Users')

headers = {'Content-Type': 'application/json'}

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
            headers={'Content-Type': 'application/json'}
        )

    # メールアドレスが既に存在するかチェック
    existing_user = users_table.get_item(Key={'email': email})
    if 'Item' in existing_user:
        return Response(
            body={'error': 'このメールアドレスは既に登録されています。'},
            status_code=400,
            headers={'Content-Type': 'application/json'}
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
        headers={'Content-Type': 'application/json'}
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
            headers={'Content-Type': 'application/json'}
        )

    # メールアドレスでユーザーを検索
    response = users_table.get_item(Key={'email': email})
    user = response.get('Item')

    if not user:
        return Response(
            body={'error': 'メールアドレスまたはパスワードが正しくありません。'},
            status_code=404,
            headers={'Content-Type': 'application/json'}
        )

    # パスワードの確認
    if not bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
        return Response(
            body={'error': 'メールアドレスまたはパスワードが正しくありません。'},
            status_code=400,
            headers={'Content-Type': 'application/json'}
        )

    return Response(
        body={'user_id': user['id']},
        status_code=200,
        headers={'Content-Type': 'application/json'}
    )