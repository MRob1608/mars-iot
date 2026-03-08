import psycopg2
import os

def get_connection():
    return psycopg2.connect(
        host="rule-database",
        database="rules_db",
        user="mars_user",
        password="mars_password"
    )

