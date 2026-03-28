from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes, hmac, padding as crypto_padding
from cryptography.hazmat.backends import default_backend
import os
import json
import base64

class SecureDataHandler:
    def __init__(self, encryption_key, hmac_key):
        self.encryption_key = encryption_key
        self.hmac_key = hmac_key

    def encrypt_and_sign(self, data) -> str:
        # Serialize data to JSON
        json_data = json.dumps(data).encode('utf-8')

        # Generate a random IV
        iv = os.urandom(16)

        # Encrypt the data
        cipher = Cipher(algorithms.AES(self.encryption_key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        padded_data = self._pad(json_data)
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()

        # Compute HMAC
        h = hmac.HMAC(self.hmac_key, hashes.SHA256(), backend=default_backend())
        h.update(iv + ciphertext)
        signature = h.finalize()

        # Combine IV, ciphertext, and signature
        result = iv + ciphertext + signature
        return base64.b64encode(result).decode('utf-8')

    def decrypt_and_verify(self, encrypted_data) -> dict:
        # Decode from base64
        data = base64.b64decode(encrypted_data.encode('utf-8'))

        # Extract IV, ciphertext, and signature
        iv = data[:16]
        ciphertext = data[16:-32]
        signature = data[-32:]

        # Verify HMAC
        h = hmac.HMAC(self.hmac_key, hashes.SHA256(), backend=default_backend())
        h.update(iv + ciphertext)
        h.verify(signature)

        # Decrypt the data
        cipher = Cipher(algorithms.AES(self.encryption_key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        plaintext = self._unpad(padded_plaintext)

        # Parse JSON
        data = json.loads(plaintext.decode('utf-8'))

        return data

    def _pad(self, data):
        padder = crypto_padding.PKCS7(algorithms.AES.block_size).padder()
        return padder.update(data) + padder.finalize()

    def _unpad(self, padded_data):
        unpadder = crypto_padding.PKCS7(algorithms.AES.block_size).unpadder()
        return unpadder.update(padded_data) + unpadder.finalize()

if __name__ == "__main__":
    from utils.helpers import load_config

    SECRETS_FILE_NAME = 'secrets.ini'

    script_dir = os.path.dirname(os.path.abspath(__file__))

    config = load_config(script_dir, SECRETS_FILE_NAME)        
    encryption_key = base64.b64decode(config.get('security_keys', 'encryption'))
    hmac_key = base64.b64decode(config.get('security_keys', 'hmac'))

    # random_bytes = os.urandom(32)
    # random_string = base64.b64encode(random_bytes).decode('utf-8')

    # print(random_bytes)
    # print(random_string)

    handler = SecureDataHandler(encryption_key, hmac_key)

    # Encrypting data
    data = {"temperature": 25.5, "humidity": 60, "pressure": 1013.25}
    encrypted = handler.encrypt_and_sign(data)
    print(f"Encrypted: {encrypted}")

    # Decrypting data
    decrypted = handler.decrypt_and_verify(encrypted)
    print(f"Decrypted: {decrypted}")

