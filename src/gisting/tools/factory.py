from gisting.shopify.client import AdminClient
from gisting.tools.attempts import FailureCounter
from gisting.tools.cache import OrderCache
from gisting.tools.lookup_order import LookupDeps, LookupOrder
from gisting.tools.policy import LookupPolicy


def build_lookup(
    client: AdminClient,
    cache: OrderCache,
    attempts: FailureCounter,
    policy: LookupPolicy,
    email_secret: str,
) -> LookupOrder:
    return LookupOrder(LookupDeps(client, cache, attempts, policy, email_secret))
