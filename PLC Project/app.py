from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify  # Flask 웹 서버 관련 모듈 가져오기
import oracle_conn  # 오라클 데이터베이스 연결용 사용자 정의 모듈
import paho.mqtt.client as mqtt  # MQTT 통신을 위한 모듈
from datetime import datetime  # 시간 관련 기능 사용을 위한 모듈

app = Flask(__name__)  # Flask 애플리케이션 객체 생성
app.secret_key = 'your_secret_key_here'  # 세션 보안을 위한 암호화 키 설정

# MQTT 브로커 연결 정보 설정
BROKER = "192.168.1.6"  # MQTT 브로커 IP 주소
PORT = 1883  # MQTT 포트 (기본값)
TOPIC = "esp32/led"  # 구독/발행할 토픽 이름

mqtt_client = mqtt.Client()  # MQTT 클라이언트 인스턴스 생성
mqtt_client.connect(BROKER, PORT, 60)  # 브로커에 연결 (60초 타임아웃)

# LED 사용 정보를 저장하는 딕셔너리 (메모리 상 유지됨)
led_usage = {
    "on_time": None,  # LED가 켜진 시간
    "off_time": None,  # LED가 꺼진 시간
    "duration_sec": 0,  # 총 켜져 있던 시간(초)
    "power_kwh": 0,  # 사용 전력량(kWh)
    "co2_kg": 0,  # 발생한 CO2량(kg)
    "status": "off"  # 현재 상태
}

WATT = 10.0  # LED 소비 전력 (Watt)
CO2_FACTOR = 0.4781  # 전력당 CO2 배출 계수 (kgCO2/kWh)

def publish_led_message(status):  # MQTT 메시지를 발행하는 함수
    print(f"📡 MQTT Publish: {status}")  # 콘솔 출력
    mqtt_client.publish(TOPIC, status)  # 해당 토픽으로 메시지 발행

def save_led_usage_to_db(usage):  # DB에 LED 사용 이력 저장
    try:
        conn = oracle_conn.get_connection()  # DB 연결
        cursor = conn.cursor()  # 커서 생성
        sql = """
            INSERT INTO LED_USAGE_LOG (ON_TIME, OFF_TIME, DURATION_HR, POWER_KWH, CO2_KG)
            VALUES (:1, :2, :3, :4, :5)
        """  # 사용 이력 저장 SQL문
        cursor.execute(sql, (
            usage['on_time'],
            usage['off_time'],
            usage['duration_sec'] / 3600.0,  # 초 단위를 시간으로 변환
            usage['power_kwh'],
            usage['co2_kg']
        ))
        conn.commit()  # 트랜잭션 커밋
    except Exception as e:
        print(f"DB 저장 실패: {e}")  # 예외 메시지 출력
    finally:
        try:
            cursor.close()  # 커서 종료
            conn.close()  # 연결 종료
        except:
            pass  # 예외 무시

def handle_led_status(msg):  # LED 상태를 처리하고 사용 이력을 계산하는 함수
    now = datetime.now()  # 현재 시간
    if msg == "on":  # LED 켜기
        led_usage["on_time"] = now
        led_usage["off_time"] = None
        led_usage["duration_sec"] = 0
        led_usage["power_kwh"] = 0
        led_usage["co2_kg"] = 0
        led_usage["status"] = "on"
    elif msg == "off" and led_usage["on_time"]:  # LED 끄기
        led_usage["off_time"] = now
        duration_sec = (led_usage["off_time"] - led_usage["on_time"]).total_seconds()  # 시간 차 계산
        power_kwh = (WATT / 1000.0) * (duration_sec / 3600.0)  # 전력 사용량 계산
        co2_kg = power_kwh * CO2_FACTOR  # CO2 배출량 계산
        led_usage["duration_sec"] = duration_sec
        led_usage["power_kwh"] = power_kwh
        led_usage["co2_kg"] = co2_kg
        led_usage["status"] = "off"
        save_led_usage_to_db(led_usage)  # DB 저장

@app.route('/')  # 루트 경로 요청 시 실행
def index():
    return render_template('index.html')  # index.html 반환

@app.route('/erp/led_log')  # ERP LED 로그 페이지
def erp_led_log_page():
    if 'operator_id' not in session:  # 로그인 안 됐을 경우
        flash('⚠️ 로그인 필요')
        return redirect(url_for('login'))  # 로그인 페이지로 리다이렉트
    return render_template('erp.html')  # erp.html 렌더링

@app.route('/erp/led_log_data')  # ERP LED 로그 데이터 API
def erp_led_log_data():
    try:
        conn = oracle_conn.get_connection()  # DB 연결
        if conn is None:
            return jsonify({"error": "오라클 DB 연결 실패"}), 500
        cursor = conn.cursor()
        sql = """
        SELECT ON_TIME, OFF_TIME, DURATION_HR, POWER_KWH, CO2_KG
        FROM (
            SELECT ON_TIME, OFF_TIME, DURATION_HR, POWER_KWH, CO2_KG
            FROM LED_USAGE_LOG
            ORDER BY ID DESC
        )
        WHERE ROWNUM = 1
        """  # 최신 데이터 1건 조회
        cursor.execute(sql)
        row = cursor.fetchone()
        if row:
            on_time, off_time, duration_hr, power_kwh, co2_kg = row
            duration_sec = duration_hr * 3600.0
            now = datetime.now()
            if on_time and (off_time is None):
                duration_sec += (now - on_time).total_seconds()
                duration_hr = duration_sec / 3600.0
                power_kwh = (WATT / 1000.0) * duration_hr
                co2_kg = power_kwh * CO2_FACTOR
            return jsonify({
                "on_time": on_time.strftime('%Y-%m-%d %H:%M:%S') if on_time else None,
                "off_time": off_time.strftime('%Y-%m-%d %H:%M:%S') if off_time else None,
                "duration_sec": int(duration_sec),
                "power_kwh": round(power_kwh, 6),
                "co2_kg": round(co2_kg, 6)
            })
        else:
            return jsonify({"error": "LED 사용 기록이 없습니다."}), 404
    except Exception as e:
        import traceback
        traceback.print_exc()  # 오류 스택 출력
        return jsonify({"error": f"DB 조회 실패: {str(e)}"}), 500
    finally:
        try:
            cursor.close()
            conn.close()
        except:
            pass

@app.route('/mes/led_control')  # MES LED 제어 페이지
def mes_led_control_page():
    if 'operator_id' not in session:
        flash('⚠️ 로그인 필요')
        return redirect(url_for('login'))
    return render_template('mes.html')

@app.route('/mes/led_control', methods=['POST'])  # MES 제어 API
def mes_led_control():
    data = request.json
    status = data.get('status')
    if status in ['on', 'off']:
        publish_led_message(status)  # MQTT 발행
        handle_led_status(status)  # 상태 기록
        return {"message": f"LED {status} 처리됨"}, 200
    return {"error": "Invalid status"}, 400

@app.route('/mes/led_status')  # MES LED 상태 조회 API
def mes_led_status():
    status = led_usage["status"]
    on_time = led_usage["on_time"]
    off_time = led_usage["off_time"]
    return jsonify({
        "status": status,
        "on_time": on_time.strftime('%Y-%m-%d %H:%M:%S') if on_time else None,
        "off_time": off_time.strftime('%Y-%m-%d %H:%M:%S') if off_time else None
    })

@app.route('/login', methods=['GET', 'POST'])  # 로그인 페이지 및 인증 처리
def login():
    if request.method == 'POST':
        operator_id = request.form['username']
        password = request.form['password']
        conn = oracle_conn.get_connection()
        cursor = conn.cursor()
        sql = "SELECT * FROM USERS WHERE OPERATOR_ID = :1 AND PASSWORD = :2"
        cursor.execute(sql, (operator_id, password))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        if user:
            session['operator_id'] = operator_id
            flash('✅ 로그인 성공')
            return redirect(url_for('index'))
        else:
            flash('❌ 아이디 또는 비밀번호 오류')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])  # 회원가입
def register():
    if request.method == 'POST':
        operator_id = request.form['userid']
        password = request.form['password']
        conn = oracle_conn.get_connection()
        cursor = conn.cursor()
        try:
            sql = "INSERT INTO USERS (OPERATOR_ID, PASSWORD) VALUES (:1, :2)"
            cursor.execute(sql, (operator_id, password))
            conn.commit()
            flash('✅ 회원가입 성공')
            return redirect(url_for('login'))
        except Exception as e:
            conn.rollback()
            flash(f'❌ 회원가입 실패: {str(e)}')
            return redirect(url_for('register'))
        finally:
            cursor.close()
            conn.close()
    return render_template('register.html')

@app.route('/forgot_password')  # 비밀번호 찾기 페이지
def forgot_password():
    return render_template('forgot_password.html')

@app.route('/logout')  # 로그아웃
def logout():
    session.pop('operator_id', None)
    flash('✅ 로그아웃 성공')
    return redirect(url_for('login'))

@app.route('/test_db')  # DB 연결 테스트용 API
def test_db():
    try:
        conn = oracle_conn.get_connection()
        if conn is None:
            return "❌ 오라클 DB 연결 실패"
        cursor = conn.cursor()
        sql = "SELECT OPERATOR_ID, CREATED_AT FROM USERS WHERE ROWNUM = 1"
        cursor.execute(sql)
        result = cursor.fetchone()
        if result:
            operator_id, created_at = result
            return f"✅ 오라클 연결 성공<br>첫 사용자: {operator_id}<br>가입일: {created_at}"
        else:
            return "⚠️ USERS 테이블에 데이터가 없습니다."
    except Exception as e:
        return f"❌ DB 조회 실패: {str(e)}"
    finally:
        try:
            cursor.close()
            conn.close()
        except:
            pass

@app.route('/mes')  # MES 메인 페이지
def mes_page():
    if 'operator_id' not in session:
        flash('⚠️ 로그인 필요')
        return redirect(url_for('login'))
    return render_template('mes.html')

@app.route('/erp')  # ERP 메인 페이지
def erp_page():
    if 'operator_id' not in session:
        flash('⚠️ 로그인 필요')
        return redirect(url_for('login'))
    return render_template('erp.html')

if __name__ == '__main__':  # 메인 모듈로 실행 시
    app.run(debug=True)  # 디버그 모드로 Flask 서버 실행
