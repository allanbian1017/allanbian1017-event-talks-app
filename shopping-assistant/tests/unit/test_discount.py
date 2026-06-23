# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from app.agent import DISCOUNT_CODES, redeem_discount_code


def reset_discount_codes():
    for code in DISCOUNT_CODES:
        DISCOUNT_CODES[code]["redeemed"] = False
        DISCOUNT_CODES[code]["user_id"] = None


def test_redeem_valid_codes():
    reset_discount_codes()
    # Redeem WELCOME50
    res = redeem_discount_code("WELCOME50", "user1")
    assert res["status"] == "success"
    assert "successfully redeemed" in res["message"]

    # Redeem SUMMER20
    res = redeem_discount_code("SUMMER20", "user2")
    assert res["status"] == "success"
    assert "successfully redeemed" in res["message"]


def test_redeem_invalid_code():
    reset_discount_codes()
    res = redeem_discount_code("INVALID100", "user1")
    assert res["status"] == "error"
    assert "Invalid discount code" in res["message"]


def test_redeem_empty_user_id():
    reset_discount_codes()
    res = redeem_discount_code("WELCOME50", "")
    assert res["status"] == "error"
    assert "user ID is required" in res["message"]


def test_single_use_constraint():
    reset_discount_codes()
    # First redemption succeeds
    res = redeem_discount_code("WELCOME50", "user1")
    assert res["status"] == "success"

    # Second redemption fails
    res = redeem_discount_code("WELCOME50", "user2")
    assert res["status"] == "error"
    assert "already been redeemed" in res["message"]
