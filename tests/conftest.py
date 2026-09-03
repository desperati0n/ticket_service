import os


# Unit tests use deterministic in-memory repositories; integration runs can opt into mysql_mongo.
os.environ["STORAGE_BACKEND"] = "memory"

