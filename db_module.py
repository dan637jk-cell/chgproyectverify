import mysql.connector
from mysql.connector import errorcode
import json
import os
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
load_dotenv()

class ConnectDB:
    def __init__(self, user_db, password_db, host_db, port_db, database="strawberry_platform"):
        self.user_db = user_db
        self.password_db = password_db
        self.host_db = host_db
        # Ensure port is int
        try:
            self.port_db = int(port_db) if port_db is not None else None
        except ValueError:
            self.port_db = None
        self.database = database
        self.connection = None
        self.connect()

    def connect(self):
        try:
            if self.port_db is None:
                raise mysql.connector.Error(msg="Invalid MySQL port (None)")
            self.connection = mysql.connector.connect(
                user=self.user_db,
                password=self.password_db,
                host=self.host_db,
                port=self.port_db,
                database=self.database
            )
            print(f"[DB] Connected to MySQL database '{self.database}'.")
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_BAD_DB_ERROR:
                print(f"[DB] Database '{self.database}' not found. Attempting creation...")
                try:
                    tmp_conn = mysql.connector.connect(
                        user=self.user_db,
                        password=self.password_db,
                        host=self.host_db,
                        port=self.port_db
                    )
                    cursor = tmp_conn.cursor()
                    cursor.execute(f"CREATE DATABASE `{self.database}`")
                    cursor.close()
                    tmp_conn.close()
                    self.connection = mysql.connector.connect(
                        user=self.user_db,
                        password=self.password_db,
                        host=self.host_db,
                        port=self.port_db,
                        database=self.database
                    )
                    print(f"[DB] Database '{self.database}' created and connected.")
                except mysql.connector.Error as err2:
                    print(f"[DB][FATAL] Cannot create database '{self.database}': {err2}")
                    self.connection = None
            else:
                print(f"[DB][ERROR] Connection failed: {err}")
                self.connection = None

    def close(self):
        if self.connection and self.connection.is_connected():
            self.connection.close()
            print(f"Connection to database '{self.database}' closed.")

    def _ensure_connection(self):
        """Reconnect if connection is lost."""
        try:
            if not self.connection or not self.connection.is_connected():
                print('[DB] Reconnecting MySQL...')
                self.connect()
        except Exception:
            print('[DB] is_connected check failed; forcing reconnect')
            self.connect()

    def execute_query(self, query, params=None, retries: int = 1):
        self._ensure_connection()
        if not self.connection:
            print("No database connection.")
            return False
        try:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            self.connection.commit()
            cursor.close()
            return True
        except mysql.connector.Error as err:
            print(f"Error executing query: {err}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            # Retry once on lost connection errors
            if retries > 0 and getattr(err, 'errno', None) in (errorcode.CR_SERVER_GONE_ERROR, errorcode.CR_SERVER_LOST):
                print('[DB] Retry after lost connection...')
                self.connect()
                return self.execute_query(query, params, retries=retries-1)
            return False

    def execute_read_query(self, query, params=None, retries: int = 1):
        self._ensure_connection()
        if not self.connection:
            print("No database connection.")
            return None
        try:
            cursor = self.connection.cursor()
            cursor.execute(query, params)
            results = cursor.fetchall()
            cursor.close()
            return results
        except mysql.connector.Error as err:
            print(f"Error executing read query: {err}")
            if retries > 0 and getattr(err, 'errno', None) in (errorcode.CR_SERVER_GONE_ERROR, errorcode.CR_SERVER_LOST):
                print('[DB] Retry read after lost connection...')
                self.connect()
                return self.execute_read_query(query, params, retries=retries-1)
            return None

class AccountsDBTools:
    def __init__(self, user_db, password_db, host_db, port_db, database="strawberry_platform"):
        self.db_connection = ConnectDB(user_db, password_db, host_db, port_db, database)
        if not self.db_connection.connection:
            raise RuntimeError("MySQL connection failed. Check credentials / network.")
        self.create_users_table()
        self.create_websites_table()
        self.create_chat_histories_table()
        self.create_wallets_table()
        self.create_token_deposits_table()
        self.create_configs_system_web3_table()

    def create_users_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS users_accounts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(255) UNIQUE,
            password VARCHAR(255),
            balance_usd DECIMAL(14, 4) DEFAULT 0.00
        ) ENGINE=InnoDB
        """
        self.db_connection.execute_query(query)
        print("[DB] Table users_accounts ready.")

    def create_websites_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS websites (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            name VARCHAR(255),
            file_name VARCHAR(255),
            url VARCHAR(2048),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users_accounts(id) ON DELETE CASCADE,
            UNIQUE KEY (user_id, name)
        ) ENGINE=InnoDB
        """
        self.db_connection.execute_query(query)
        print("[DB] Table websites ready.")

    def create_chat_histories_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS chat_histories (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            hashchat VARCHAR(255) UNIQUE,
            title VARCHAR(255),
            history JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users_accounts(id) ON DELETE CASCADE
        ) ENGINE=InnoDB
        """
        self.db_connection.execute_query(query)
        print("[DB] Table chat_histories ready.")

    def register_new_user(self, username, password):
        # Pre-verificar duplicados
        query_check_user = "SELECT username FROM users_accounts WHERE username = %s"
        params_check_user = (username,)
        result_user = self.db_connection.execute_read_query(query_check_user, params_check_user)

        if result_user:
            # Mensaje solicitado en español
            return "este usuario ya existe prueba con otro username"
        else:
            hashed_password = generate_password_hash(password)
            query_insert = """
            INSERT INTO users_accounts (username, password)
            VALUES (%s, %s)
            """
            params_insert = (username, hashed_password)
            inserted = self.db_connection.execute_query(query_insert, params_insert)
            if inserted:
                print("User registered successfully.")
                return "User registered successfully."
            else:
                # Fallback en caso de error (incluido duplicado a nivel DB)
                return "este usuario ya existe prueba con otro username"

    def login_session(self, username, password):
        query = "SELECT id, username, password FROM users_accounts WHERE username = %s"
        params = (username,)
        result = self.db_connection.execute_read_query(query, params)

        if result:
            user_data = result[0]
            if check_password_hash(user_data[2], password):
                user_info = {
                    "user_id": user_data[0],
                    "username": user_data[1]
                }
                return json.dumps(user_info)
            else:
                return json.dumps({"error": "Invalid password."})
        else:
            return json.dumps({"error": "User not found."})

    def get_website_by_name(self, user_id, name):
        query = "SELECT file_name, url FROM websites WHERE user_id = %s AND name = %s"
        params = (user_id, name)
        result = self.db_connection.execute_read_query(query, params)
        if result:
            base_url = os.getenv('BASE_URL', 'http://localhost:8080').rstrip('/')
            relative_url = result[0][1]
            full_url = f"{base_url}{relative_url}" if not relative_url.startswith('http') else relative_url
            return {"file_name": result[0][0], "url": full_url}
        return None

    def check_website_exists(self, user_id, name):
        query = "SELECT id FROM websites WHERE user_id = %s AND name = %s"
        params = (user_id, name)
        result = self.db_connection.execute_read_query(query, params)
        return result is not None and len(result) > 0

    def save_website(self, user_id, url, name, file_name):
        query = """
        INSERT INTO websites (user_id, name, file_name, url)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
        url = VALUES(url), file_name = VALUES(file_name)
        """
        params = (user_id, name, file_name, url)
        self.db_connection.execute_query(query, params)
        print(f"[DB] Website saved user={user_id} name={name}")

    def get_user_history(self, user_id):
        query_chats = "SELECT hashchat, title, updated_at FROM chat_histories WHERE user_id = %s ORDER BY updated_at DESC"
        query_websites = "SELECT name, url, updated_at FROM websites WHERE user_id = %s ORDER BY updated_at DESC"
        params = (user_id,)
        
        chat_history = self.db_connection.execute_read_query(query_chats, params)
        website_history = self.db_connection.execute_read_query(query_websites, params)
        
        base_url = os.getenv('BASE_URL', 'http://localhost:8080').rstrip('/')

        return {
            "chats": [{"hashchat": c[0], "title": c[1], "updated_at": c[2].isoformat()} for c in chat_history] if chat_history else [],
            "websites": [{"name": w[0], "url": f"{base_url}{w[1]}" if not w[1].startswith('http') else w[1], "updated_at": w[2].isoformat()} for w in website_history] if website_history else []
        }

    def save_chat_history(self, user_id, hashchat, title, history):
        query = """
        INSERT INTO chat_histories (user_id, hashchat, title, history)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
        title = VALUES(title), history = VALUES(history)
        """
        params = (user_id, hashchat, title, json.dumps(history))
        self.db_connection.execute_query(query, params)
        print(f"[DB] Chat history saved user={user_id} hash={hashchat}")

    def load_chat_history(self, hashchat, user_id):
        query = "SELECT history FROM chat_histories WHERE hashchat = %s AND user_id = %s"
        params = (hashchat, user_id)
        result = self.db_connection.execute_read_query(query, params)
        if result and result[0][0]:
            return json.loads(result[0][0])
        return None

    def delete_website(self, user_id, name):
        query = "DELETE FROM websites WHERE user_id = %s AND name = %s"
        params = (user_id, name)
        return self.db_connection.execute_query(query, params)

    def delete_chat_history(self, user_id, hashchat):
        query = "DELETE FROM chat_histories WHERE user_id = %s AND hashchat = %s"
        params = (user_id, hashchat)
        return self.db_connection.execute_query(query, params)

    def delete_all_chat_history(self, user_id):
        query = "DELETE FROM chat_histories WHERE user_id = %s"
        params = (user_id,)
        return self.db_connection.execute_query(query, params)

    def get_latest_chat(self, user_id):
        query = "SELECT hashchat FROM chat_histories WHERE user_id = %s ORDER BY updated_at DESC LIMIT 1"
        params = (user_id,)
        result = self.db_connection.execute_read_query(query, params)
        if result:
            return result[0][0]
        return None

    def get_user_balance(self, user_id):
        query = "SELECT balance_usd FROM users_accounts WHERE id = %s"
        params = (user_id,)
        result = self.db_connection.execute_read_query(query, params)
        if result:
            return result[0][0]
        return None

    def update_user_balance(self, user_id, new_balance):
        query = "UPDATE users_accounts SET balance_usd = %s WHERE id = %s"
        params = (new_balance, user_id)
        return self.db_connection.execute_query(query, params)

    # --- New helpers for robust republish detection ---
    def get_website_by_file(self, user_id, file_name):
        """Return website row by file_name for a user."""
        query = "SELECT name, file_name, url FROM websites WHERE user_id = %s AND file_name = %s"
        params = (user_id, file_name)
        result = self.db_connection.execute_read_query(query, params)
        if result:
            base_url = os.getenv('BASE_URL', 'http://localhost:8080').rstrip('/')
            relative_url = result[0][2]
            full_url = f"{base_url}{relative_url}" if not relative_url.startswith('http') else relative_url
            return {"name": result[0][0], "file_name": result[0][1], "url": full_url}
        return None

    def update_website_by_file(self, user_id, file_name, new_name, new_url):
        """Update a website row matched by (user_id, file_name). Returns True if updated or inserted."""
        # Try update first
        query_update = """
        UPDATE websites
        SET name = %s, url = %s
        WHERE user_id = %s AND file_name = %s
        """
        params_update = (new_name, new_url, user_id, file_name)
        updated = self.db_connection.execute_query(query_update, params_update)
        if updated:
            return True
        # If update failed due to no row or other reason, try insert as fallback
        return self.save_website(user_id, new_url, new_name, file_name)

    # --- Wallet & Deposits integration for SPL token ---
    def create_wallets_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS user_wallets (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            wallet_address VARCHAR(100) UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users_accounts(id) ON DELETE CASCADE
        ) ENGINE=InnoDB
        """
        self.db_connection.execute_query(query)
        print("Table 'user_wallets' created or already exists.")

    def create_token_deposits_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS token_deposits (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            wallet_address VARCHAR(100) NOT NULL,
            amount_tokens DECIMAL(36,12) NOT NULL,
            amount_usd DECIMAL(18,8) NOT NULL,
            signature_tx VARCHAR(120) UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users_accounts(id) ON DELETE CASCADE,
            INDEX (wallet_address)
        ) ENGINE=InnoDB
        """
        self.db_connection.execute_query(query)
        print("Table 'token_deposits' created or already exists.")

    def create_configs_system_web3_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS configs_system_web3 (
            id INT AUTO_INCREMENT PRIMARY KEY,
            token_address VARCHAR(120) NOT NULL,
            price_usd DECIMAL(30, 12) DEFAULT 0,
            market_cap_usd DECIMAL(40, 2) DEFAULT 0,
            fdv_usd DECIMAL(40, 2) DEFAULT 0,
            liquidity_usd DECIMAL(40, 2) DEFAULT 0,
            volume24_usd DECIMAL(40, 2) DEFAULT 0,
            last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY(token_address)
        ) ENGINE=InnoDB
        """
        self.db_connection.execute_query(query)
        print("Table 'configs_system_web3' created or already exists.")

    def upsert_token_metrics(self, token_address: str, metrics: dict):
        query = """
        INSERT INTO configs_system_web3 (token_address, price_usd, market_cap_usd, fdv_usd, liquidity_usd, volume24_usd)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            price_usd = VALUES(price_usd),
            market_cap_usd = VALUES(market_cap_usd),
            fdv_usd = VALUES(fdv_usd),
            liquidity_usd = VALUES(liquidity_usd),
            volume24_usd = VALUES(volume24_usd)
        """
        params = (
            token_address,
            metrics.get('price_usd') or 0,
            metrics.get('market_cap_usd') or 0,
            metrics.get('fdv_usd') or 0,
            metrics.get('liquidity_usd') or 0,
            metrics.get('volume24_usd') or 0,
        )
        return self.db_connection.execute_query(query, params)

    def fetch_token_metrics(self, token_address: str):
        query = "SELECT price_usd, market_cap_usd, fdv_usd, liquidity_usd, volume24_usd, last_update FROM configs_system_web3 WHERE token_address = %s"
        res = self.db_connection.execute_read_query(query, (token_address,))
        if res:
            row = res[0]
            return {
                'price_usd': float(row[0]),
                'market_cap_usd': float(row[1]),
                'fdv_usd': float(row[2]),
                'liquidity_usd': float(row[3]),
                'volume24_usd': float(row[4]),
                'last_update': str(row[5])
            }
        return None

    def link_wallet_to_user(self, user_id: int, wallet_address: str):
        query = "INSERT IGNORE INTO user_wallets (user_id, wallet_address) VALUES (%s, %s)"
        self.db_connection.execute_query(query, (user_id, wallet_address))

    def get_user_by_wallet(self, wallet_address: str):
        """Return {'user_id': int, 'wallet_address': str} or None.

        Old code returned just user_id (int) which caused ambiguity in caller code
        expecting dict-like access. This normalizes the return type.
        """
        query = "SELECT user_id, wallet_address FROM user_wallets WHERE wallet_address = %s"
        res = self.db_connection.execute_read_query(query, (wallet_address,))
        if res:
            return { 'user_id': res[0][0], 'wallet_address': res[0][1] }
        return None

    def deposit_exists(self, signature_tx: str) -> bool:
        query = "SELECT 1 FROM token_deposits WHERE signature_tx = %s"
        res = self.db_connection.execute_read_query(query, (signature_tx,))
        return bool(res)

    def record_deposit(self, user_id: int, wallet_address: str, amount_tokens, amount_usd, signature_tx: str):
        query = ("INSERT INTO token_deposits (user_id, wallet_address, amount_tokens, amount_usd, signature_tx) "
                 "VALUES (%s, %s, %s, %s, %s)")
        return self.db_connection.execute_query(query, (user_id, wallet_address, amount_tokens, amount_usd, signature_tx))

