import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def generate_vapid_keys():
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_number = private_key.private_numbers().private_value.to_bytes(32, "big")
    public_bytes = private_key.public_key().public_bytes(
        encoding=Encoding.X962,
        format=PublicFormat.UncompressedPoint,
    )
    private_value = base64.urlsafe_b64encode(private_number).rstrip(b"=").decode("ascii")
    public_value = base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode("ascii")
    return private_value, public_value


if __name__ == "__main__":
    private_value, public_value = generate_vapid_keys()
    print("VAPID_PUBLIC_KEY:")
    print(public_value)
    print("VAPID_PRIVATE_KEY (keep secret; do not commit):")
    print(private_value)
