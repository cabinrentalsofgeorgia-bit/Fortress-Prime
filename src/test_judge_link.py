"""
Fortress Prime — SOTA Judge Link Test
Tests the connection to the BGE Reranker on Spark 1.
"""
import os
import sys
import requests
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import SPARK_02_IP

# --- CONFIG ---
JUDGE_URL = f"http://{SPARK_02_IP}:8000/rerank"


def test_link():
    print(f"TESTING CONNECTION TO SOTA JUDGE: {JUDGE_URL}")

    payload = {
        "query": "Who owns the land at Toccoa Heights?",
        "documents": [
            "The quick brown fox jumps over the dog.",
            "The warranty deed conveys title to Gary M. Knight for Lot 14 in Toccoa Heights subdivision.",
            "Python scripts are useful for automation and data processing.",
            "The plat of survey for Phase Two sets forth Lots 13-24 of the Subdivision.",
            "Invoice #9066 from Cabin Rentals of Georgia for cleaning services.",
        ]
    }

    try:
        response = requests.post(JUDGE_URL, json=payload, timeout=30)
        if response.status_code == 200:
            results = response.json()['ranked']
            print("\nJUDGE IS ONLINE. Ranking Results:\n")
            for rank, item in enumerate(results):
                score = item['score']
                bar = "#" * max(1, int((score + 10) * 3))  # visual bar
                print(f"   #{rank+1} [Score: {score:>8.4f}] {bar}")
                print(f"      {item['text'][:100]}")
                print()
            print("If the warranty deed scored highest, the Judge is working correctly.")
        else:
            print(f"SERVER ERROR: {response.status_code} {response.text}")

    except requests.exceptions.ConnectionError:
        print("CONNECTION REFUSED — Judge not running yet.")
        print("   Check: ssh admin@192.168.0.104 'tail -20 ~/reranker.log'")
    except requests.exceptions.Timeout:
        print("TIMEOUT — Model may still be loading.")
        print("   Check: ssh admin@192.168.0.104 'tail -20 ~/reranker.log'")
    except Exception as e:
        print(f"ERROR: {e}")


if __name__ == "__main__":
    test_link()
