import cx_Oracle

def get_connection():
    try:
        dsn = cx_Oracle.makedsn("localhost", 1521, service_name="xe")
        connection = cx_Oracle.connect(user="EMS_PROJECT", password="1234", dsn=dsn)
        print("✅ 오라클 연결 성공")
        return connection
    except Exception as e:
        print("❌ 오라클 연결 실패:", str(e))
        return None

# ✅ 이 부분을 추가해서 테스트 실행
if __name__ == '__main__':
    get_connection()
