import random
import uuid
from datetime import datetime

import boto3
from boto3.dynamodb.conditions import Attr
from chalice import Chalice, NotFoundError, Response

dynamodb = boto3.resource(
    "dynamodb", region_name="ap-northeast-1", endpoint_url="http://localhost:8000"
)
app = Chalice(app_name="docomo_backend")
headers = {}  # 要変更

users_table = dynamodb.Table("Users")
sessions_table = dynamodb.Table("Sessions")
themes_table = dynamodb.Table("Themes")


@app.route("/session", methods=["POST"])
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
        return Response(body=response_body, status_code=200, headers={})


def get_random_theme():
    response = themes_table.scan()
    themes = response["Items"]
    return random.choice(themes) if themes else None


@app.route("/end_session/{session_id}", methods=["GET"])
def end_session():
    session_id = app.current_request.query_params.get("session_id")

    session = sessions_table.get_item(Key={"ID": session_id})["Item"]
    session["ISEND"] = True
    sessions_table.put_item(Item=session)
    response_body = {"message": "Session ended"}
    return Response(body=response_body, status_code=200, headers={})


@app.route("/add_theme", methods=["POST"])
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


@app.route("/get_zoom_url/{id}")
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
