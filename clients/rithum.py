"""Rithum (ChannelAdvisor) API client — adapted from ascot/rithum_client.py.

Handles OAuth2 authentication, order fetching, product lookup, and
fulfillment posting with production-grade retry logic.
"""
import logging
import threading
import time
from typing import Iterator

import requests
from requests.auth import HTTPBasicAuth

import config

logger = logging.getLogger(__name__)


class RithumClient:
    """Thread-safe Rithum API client with automatic token management."""

    def __init__(
        self,
        app_id: str | None = None,
        secret: str | None = None,
        refresh_token: str | None = None,
    ):
        self.app_id = app_id or config.RITHUM_APP_ID
        self.secret = secret or config.RITHUM_SECRET
        self.refresh_token = refresh_token or config.RITHUM_REFRESH_TOKEN
        self._access_token: str | None = None
        self._token_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self) -> str:
        """Exchange refresh token for a new access token."""
        resp = requests.post(
            config.RITHUM_TOKEN_URL,
            auth=HTTPBasicAuth(self.app_id, self.secret),
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]
        with self._token_lock:
            self._access_token = token
        logger.info("Rithum: authenticated successfully")
        return token

    def _get_headers(self) -> dict:
        """Get Authorization headers, authenticating if needed."""
        with self._token_lock:
            token = self._access_token
        if not token:
            token = self.authenticate()
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------
    # Generic request with retry
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        max_retries: int | None = None,
        **kwargs,
    ) -> requests.Response:
        """Make an API request with retry logic (401 re-auth, 429 rate limit, 5xx backoff)."""
        retries = max_retries or config.RITHUM_MAX_RETRIES
        kwargs.setdefault("timeout", 60)

        for attempt in range(retries):
            try:
                kwargs["headers"] = {**self._get_headers(), **kwargs.get("headers", {})}
                resp = requests.request(method, url, **kwargs)

                if resp.status_code == 401:
                    logger.warning("Rithum: 401 — re-authenticating (attempt %d)", attempt + 1)
                    self.authenticate()
                    continue

                if resp.status_code == 429:
                    logger.warning("Rithum: 429 rate limited — sleeping %ds", config.RITHUM_RATE_LIMIT_SLEEP)
                    time.sleep(config.RITHUM_RATE_LIMIT_SLEEP)
                    continue

                if resp.status_code >= 500:
                    wait = 10 * (attempt + 1)
                    logger.warning("Rithum: %d server error — retrying in %ds", resp.status_code, wait)
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                return resp

            except requests.ConnectionError:
                wait = 5 * (attempt + 1)
                logger.warning("Rithum: connection error — retrying in %ds", wait)
                time.sleep(wait)

        raise RuntimeError(f"Rithum API request failed after {retries} attempts: {method} {url}")

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def fetch_unshipped_orders(
        self,
        dc_name: str | None = None,
        page_size: int | None = None,
    ) -> Iterator[dict]:
        """
        Yield unshipped orders with their items from Rithum.

        If dc_name is provided, only yields orders that have at least one
        item with that DistributionCenterName.
        """
        ps = page_size or config.RITHUM_PAGE_SIZE
        base_filter = (
            f"ProfileID eq {config.RITHUM_PROFILE_ID}"
            f" and ShippingStatus eq 'Unshipped'"
            f" and PaymentStatus eq 'Cleared'"
        )

        skip = 0
        while True:
            url = (
                f"{config.RITHUM_API_BASE}/Orders"
                f"?$filter={base_filter}"
                f"&$expand=Items"
                f"&$orderby=CreatedDateUtc asc"
                f"&$top={ps}&$skip={skip}"
            )
            resp = self._request("GET", url)
            data = resp.json()
            orders = data.get("value", [])

            if not orders:
                break

            for order in orders:
                if dc_name:
                    # Filter to only items matching the requested DC
                    matching_items = [
                        item for item in order.get("Items", [])
                        if (item.get("DistributionCenterName") or "").strip() == dc_name
                    ]
                    if matching_items:
                        order["Items"] = matching_items
                        yield order
                else:
                    yield order

            # Rithum caps page size server-side (~100), so paginate on empty-response
            skip += len(orders)

    def get_order(self, order_id: int) -> dict:
        """Fetch a single order with items."""
        url = f"{config.RITHUM_API_BASE}/Orders({order_id})?$expand=Items"
        resp = self._request("GET", url)
        return resp.json()

    # ------------------------------------------------------------------
    # Products (for EAN/MPN lookup)
    # ------------------------------------------------------------------

    def get_product_by_sku(self, sku: str) -> dict | None:
        """Look up a product by SKU to get EAN, MPN, etc."""
        url = (
            f"{config.RITHUM_API_BASE}/Products"
            f"?$filter=ProfileID eq {config.RITHUM_PROFILE_ID}"
            f" and Sku eq '{sku}'"
            f"&$select=ID,Sku,UPC,EAN,MPN,Title,Brand"
            f"&$top=1"
        )
        resp = self._request("GET", url)
        products = resp.json().get("value", [])
        return products[0] if products else None

    def get_products_by_skus(self, skus: list[str]) -> dict[str, dict]:
        """
        Bulk lookup products by SKU. Returns {sku: product_data}.

        Batches into groups to avoid URL length limits.
        """
        result = {}
        batch_size = 20  # OData filter length limit

        for i in range(0, len(skus), batch_size):
            batch = skus[i:i + batch_size]
            sku_filter = " or ".join(f"Sku eq '{s}'" for s in batch)
            url = (
                f"{config.RITHUM_API_BASE}/Products"
                f"?$filter=ProfileID eq {config.RITHUM_PROFILE_ID}"
                f" and ({sku_filter})"
                f"&$select=ID,Sku,UPC,EAN,MPN,Title,Brand"
                f"&$top={batch_size}"
            )
            resp = self._request("GET", url)
            for p in resp.json().get("value", []):
                result[p["Sku"]] = p

        return result

    # ------------------------------------------------------------------
    # Fulfillments (tracking writeback)
    # ------------------------------------------------------------------

    def post_fulfillment(
        self,
        order_id: int,
        items: list[dict],
        tracking_number: str,
        carrier: str,
        ship_date: str,
    ) -> dict:
        """
        Create a fulfillment (shipment) for an order.

        items: list of {"OrderItemID": int, "Quantity": int}
        ship_date: ISO format string e.g. "2026-03-31T00:00:00Z"
        """
        url = f"{config.RITHUM_API_BASE}/Fulfillments"
        payload = {
            "OrderID": order_id,
            "Type": "Ship",
            "ShippingCarrier": carrier,
            "TrackingNumber": tracking_number,
            "ShippedDateUtc": ship_date,
            "Items": [
                {
                    "OrderItemID": item["OrderItemID"],
                    "Quantity": item["Quantity"],
                }
                for item in items
            ],
        }
        resp = self._request("POST", url, json=payload)
        result = resp.json()
        logger.info(
            "Rithum: created fulfillment for order %d, tracking %s",
            order_id, tracking_number,
        )
        return result

    def ship_order(
        self,
        order_id: int,
        tracking_number: str,
        carrier: str,
        ship_date: str,
        shipping_class: str = "",
    ) -> dict:
        """Mark an entire order as shipped (simpler than line-level fulfillment)."""
        url = f"{config.RITHUM_API_BASE}/Orders({order_id})/Ship"
        payload = {
            "TrackingNumber": tracking_number,
            "ShippingCarrier": carrier,
            "ShippedDateUtc": ship_date,
        }
        if shipping_class:
            payload["ShippingClass"] = shipping_class
        resp = self._request("POST", url, json=payload)
        logger.info("Rithum: shipped order %d, tracking %s", order_id, tracking_number)
        return resp.json() if resp.content else {}

    # ------------------------------------------------------------------
    # Distribution Centers
    # ------------------------------------------------------------------

    def get_distribution_centers(self) -> list[dict]:
        """List all distribution centers."""
        url = f"{config.RITHUM_API_BASE}/DistributionCenters"
        resp = self._request("GET", url)
        return resp.json().get("value", [])

    def get_dc(self, dc_id: int) -> dict | None:
        """Fetch a single DC by ID (works even if not in the list endpoint)."""
        try:
            resp = self._request("GET", f"{config.RITHUM_API_BASE}/DistributionCenters({dc_id})")
            return resp.json()
        except Exception:
            return None

    def get_dc_by_code(self, code: str) -> dict | None:
        """Find a DC by its Code field. Scans list + known extra IDs if not found."""
        for dc in self.get_distribution_centers():
            if (dc.get("Code") or "").strip().upper() == code.upper():
                return dc
        return None

    # ------------------------------------------------------------------
    # Fulfillment-centric flow (new pipeline)
    # ------------------------------------------------------------------

    def fetch_new_fulfillments(
        self,
        dc_id: int,
        page_size: int | None = None,
    ) -> Iterator[dict]:
        """
        Yield Fulfillments at the given DC that are ready to submit.

        Criteria: order Unshipped + Cleared payment, fulfillment
        DistributionCenterID == dc_id, ExternalFulfillmentStatus == 'New'.

        Each yielded dict carries {"Fulfillment": <fulfillment>, "Order": <order header>}.
        """
        ps = page_size or config.RITHUM_PAGE_SIZE
        base_filter = (
            f"ProfileID eq {config.RITHUM_PROFILE_ID}"
            f" and ShippingStatus eq 'Unshipped'"
            f" and PaymentStatus eq 'Cleared'"
        )

        skip = 0
        while True:
            url = (
                f"{config.RITHUM_API_BASE}/Orders"
                f"?$filter={base_filter}"
                f"&$expand=Items,Fulfillments"
                f"&$orderby=CreatedDateUtc asc"
                f"&$top={ps}&$skip={skip}"
            )
            resp = self._request("GET", url)
            orders = resp.json().get("value", [])

            if not orders:
                break

            for order in orders:
                for f in order.get("Fulfillments", []):
                    if (
                        f.get("DistributionCenterID") == dc_id
                        and f.get("ExternalFulfillmentStatus") == "New"
                    ):
                        yield {"Fulfillment": f, "Order": order}

            # Rithum caps page size server-side (~100), so we paginate as long as
            # the response isn't empty — not based on "got fewer than asked."
            skip += len(orders)

    def get_fulfillment(self, fulfillment_id: int, expand_items: bool = True) -> dict:
        """Fetch a single Fulfillment by ID, optionally expanding its items."""
        url = f"{config.RITHUM_API_BASE}/Fulfillments({fulfillment_id})"
        if expand_items:
            url += "?$expand=Items"
        resp = self._request("GET", url)
        return resp.json()

    def get_fulfillment_items(self, fulfillment_id: int) -> list[dict]:
        """List items belonging to a specific Fulfillment."""
        return self.get_fulfillment(fulfillment_id, expand_items=True).get("Items", []) or []

    def update_fulfillment(self, fulfillment_id: int, patch: dict) -> dict:
        """PATCH a Fulfillment with arbitrary fields (e.g. ExternalFulfillmentStatus)."""
        url = f"{config.RITHUM_API_BASE}/Fulfillments({fulfillment_id})"
        resp = self._request("PATCH", url, json=patch)
        logger.info("Rithum: patched fulfillment %d: %s", fulfillment_id, list(patch.keys()))
        return resp.json() if resp.content else {}

    def mark_fulfillment_pending(
        self,
        fulfillment_id: int,
        po_number: str,
    ) -> dict:
        """
        Transition a Fulfillment from 'New' -> 'Pending' and record our PO number.

        Mirrors the existing PartsUnlimited automation pattern: the
        ExternalFulfillmentNumber carries whatever identifier links Rithum back
        to our outbound PO (we use the Rithum OrderID/FulfillmentID).
        """
        return self.update_fulfillment(
            fulfillment_id,
            {
                "ExternalFulfillmentStatus": "Pending",
                "ExternalFulfillmentNumber": str(po_number),
            },
        )

    def mark_fulfillment_failed(self, fulfillment_id: int, reason: str = "") -> dict:
        """Mark a Fulfillment as Failed (submission error)."""
        patch = {"ExternalFulfillmentStatus": "Failed"}
        if reason:
            patch["ExternalFulfillmentReferenceNumber"] = reason[:50]
        return self.update_fulfillment(fulfillment_id, patch)

    def ship_fulfillment(
        self,
        fulfillment_id: int,
        tracking_number: str,
        carrier: str,
        ship_date: str,
        shipping_class: str = "",
    ) -> dict:
        """
        Post tracking for a specific Fulfillment and mark it Complete.

        ship_date: ISO format string (e.g. "2026-04-14T00:00:00Z").
        """
        patch = {
            "TrackingNumber": tracking_number,
            "ShippingCarrier": carrier,
            "ShippedDateUtc": ship_date,
            "ExternalFulfillmentStatus": "Complete",
        }
        if shipping_class:
            patch["ShippingClass"] = shipping_class
        return self.update_fulfillment(fulfillment_id, patch)
