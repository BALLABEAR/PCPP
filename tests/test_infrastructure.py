"""
Запуск:
    pip install pytest psycopg2-binary redis boto3
    pytest tests/test_infrastructure.py -v
"""

import os
import pytest
import psycopg2
import redis
import boto3
from botocore.exceptions import EndpointResolutionError, ClientError
from botocore.config import Config
from dotenv import load_dotenv
load_dotenv()

# ─── Настройки подключения (читаем из окружения, с
#
# дефолтами для локальной разработки)
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB   = os.getenv("POSTGRES_DB",   "pcpp")
POSTGRES_USER = os.getenv("POSTGRES_USER", "pcpp_user")
POSTGRES_PASS = os.getenv("POSTGRES_PASSWORD", "pcpp_password")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

MINIO_ENDPOINT        = os.getenv("MINIO_ENDPOINT",         "http://localhost:9000")
MINIO_ACCESS_KEY      = os.getenv("MINIO_ROOT_USER",        "pcpp_minio")
MINIO_SECRET_KEY      = os.getenv("MINIO_ROOT_PASSWORD",    "pcpp_minio_secret")
MINIO_BUCKET_FILES    = os.getenv("MINIO_BUCKET_FILES",     "pcpp-files")
MINIO_BUCKET_RESULTS  = os.getenv("MINIO_BUCKET_RESULTS",   "pcpp-results")


# ══════════════════════════════════════════════════════════════════════════════
#  PostgreSQL
# ══════════════════════════════════════════════════════════════════════════════

class TestPostgres:

    def test_connection(self):
        """PostgreSQL доступен и принимает подключения."""
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASS,
            connect_timeout=5,
        )
        assert conn.status == psycopg2.extensions.STATUS_READY
        conn.close()

    def test_database_exists(self):
        """База данных pcpp существует."""
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASS,
        )
        cur = conn.cursor()
        cur.execute("SELECT current_database();")
        db_name = cur.fetchone()[0]
        assert db_name == POSTGRES_DB
        cur.close()
        conn.close()

    def test_can_create_and_drop_table(self):
        """Пользователь имеет права на создание таблиц."""
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASS,
        )
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS _test_table (id SERIAL PRIMARY KEY);")
        conn.commit()
        cur.execute("DROP TABLE _test_table;")
        conn.commit()
        cur.close()
        conn.close()

    def test_write_and_read(self):
        """Запись и чтение данных работают корректно."""
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASS,
        )
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS _test_rw (value TEXT);")
        cur.execute("INSERT INTO _test_rw (value) VALUES (%s);", ("hello_pcpp",))
        conn.commit()
        cur.execute("SELECT value FROM _test_rw;")
        row = cur.fetchone()
        assert row[0] == "hello_pcpp"
        cur.execute("DROP TABLE _test_rw;")
        conn.commit()
        cur.close()
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
#  Redis
# ══════════════════════════════════════════════════════════════════════════════

class TestRedis:

    def _client(self):
        return redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            socket_connect_timeout=5,
            decode_responses=True,
        )

    def test_connection(self):
        """Redis доступен и отвечает на ping."""
        r = self._client()
        assert r.ping() is True

    def test_set_and_get(self):
        """Запись и чтение ключа работают корректно."""
        r = self._client()
        r.set("pcpp_test_key", "pcpp_test_value", ex=10)
        value = r.get("pcpp_test_key")
        assert value == "pcpp_test_value"
        r.delete("pcpp_test_key")

    def test_key_expiry(self):
        """TTL ключа устанавливается корректно."""
        r = self._client()
        r.set("pcpp_ttl_key", "value", ex=60)
        ttl = r.ttl("pcpp_ttl_key")
        assert 0 < ttl <= 60
        r.delete("pcpp_ttl_key")

    def test_delete_key(self):
        """Удаление ключа работает корректно."""
        r = self._client()
        r.set("pcpp_del_key", "value")
        r.delete("pcpp_del_key")
        assert r.get("pcpp_del_key") is None


# ══════════════════════════════════════════════════════════════════════════════
#  MinIO
# ══════════════════════════════════════════════════════════════════════════════

class TestMinio:

    def _client(self):
        return boto3.client(
            "s3",
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )

    def test_connection(self):
        """MinIO доступен и возвращает список бакетов."""
        s3 = self._client()
        response = s3.list_buckets()
        assert "Buckets" in response

    def test_files_bucket_exists(self):
        """Бакет pcpp-files существует."""
        s3 = self._client()
        buckets = [b["Name"] for b in s3.list_buckets()["Buckets"]]
        assert MINIO_BUCKET_FILES in buckets, (
            f"Бакет '{MINIO_BUCKET_FILES}' не найден. Существующие бакеты: {buckets}"
        )

    def test_results_bucket_exists(self):
        """Бакет pcpp-results существует."""
        s3 = self._client()
        buckets = [b["Name"] for b in s3.list_buckets()["Buckets"]]
        assert MINIO_BUCKET_RESULTS in buckets, (
            f"Бакет '{MINIO_BUCKET_RESULTS}' не найден. Существующие бакеты: {buckets}"
        )

    def test_upload_and_download_file(self):
        """Загрузка и скачивание файла работают корректно."""
        s3 = self._client()
        test_content = b"pcpp test file content"
        test_key = "_test/test_file.txt"

        s3.put_object(
            Bucket=MINIO_BUCKET_FILES,
            Key=test_key,
            Body=test_content,
        )

        response = s3.get_object(Bucket=MINIO_BUCKET_FILES, Key=test_key)
        downloaded = response["Body"].read()
        assert downloaded == test_content

        s3.delete_object(Bucket=MINIO_BUCKET_FILES, Key=test_key)

    def test_delete_file(self):
        """Удаление файла работает корректно."""
        s3 = self._client()
        key = "_test/to_delete.txt"
        s3.put_object(Bucket=MINIO_BUCKET_FILES, Key=key, Body=b"delete me")
        s3.delete_object(Bucket=MINIO_BUCKET_FILES, Key=key)

        with pytest.raises(ClientError) as exc:
            s3.get_object(Bucket=MINIO_BUCKET_FILES, Key=key)
        assert exc.value.response["Error"]["Code"] == "NoSuchKey"


# ══════════════════════════════════════════════════════════════════════════════
#  Интеграционный тест: все сервисы работают вместе
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegration:

    def test_all_services_reachable(self):
        """
        Все три сервиса доступны одновременно.
        Это финальная проверка готовности этапа 1.
        """
        # PostgreSQL
        conn = psycopg2.connect(
            host=POSTGRES_HOST, port=POSTGRES_PORT,
            dbname=POSTGRES_DB, user=POSTGRES_USER,
            password=POSTGRES_PASS, connect_timeout=5,
        )
        assert conn.status == psycopg2.extensions.STATUS_READY
        conn.close()

        # Redis
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT,
                        socket_connect_timeout=5)
        assert r.ping()

        # MinIO
        s3 = boto3.client(
            "s3",
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
        response = s3.list_buckets()
        assert "Buckets" in response