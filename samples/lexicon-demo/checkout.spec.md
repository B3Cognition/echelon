ARTIFACT: SPEC
TITLE: Cart Checkout with Payment Processing

REQ: CHK-001
GIVEN: a signed-in shopper with a non-empty cart
WHEN: the shopper initiates checkout via Checkout_Service
THEN: Checkout_Service MUST compute order_total from all items in the cart
OUTPUT: order_total is calculated and available for payment processing
CONSTRAINT: order_total greater-than 0 currency-units

REQ: CHK-002
GIVEN: order_total has been computed for the cart
WHEN: Checkout_Service proceeds to payment
THEN: Checkout_Service MUST create a payment_intent for the computed order_total
OUTPUT: payment_intent is created with the exact order_total amount

REQ: CHK-003
GIVEN: a payment_intent exists for the order_total
WHEN: Checkout_Service submits the payment_intent to Payment_Gateway
THEN: Payment_Gateway MUST charge the payment_intent amount
OUTPUT: payment_status is returned by Payment_Gateway indicating charge result

REQ: CHK-004
GIVEN: Payment_Gateway returns a successful charge for the payment_intent
WHEN: Checkout_Service receives the success response
THEN: Checkout_Service MUST create an order and set order_status to CONFIRMED
OUTPUT: order record exists with order_status equal to CONFIRMED

REQ: CHK-005
GIVEN: an order has been created with order_status set to CONFIRMED
WHEN: order creation completes
THEN: Checkout_Service MUST send an order_confirmation_email to the shopper
OUTPUT: order_confirmation_email is dispatched to the shopper email address

REQ: CHK-006
GIVEN: Payment_Gateway returns a declined or insufficient-funds response
WHEN: Checkout_Service receives the failure response
THEN: Checkout_Service MUST NOT create an order
OUTPUT: no order record is created and the shopper is informed of the payment failure

AC: CHK-AC-001
GIVEN: a signed-in shopper with three items in the cart totaling 150 currency-units
WHEN: the shopper completes checkout
THEN: an order exists with order_status equal to CONFIRMED, order_total equal to 150, and an order_confirmation_email has been sent

AC: CHK-AC-002
GIVEN: a signed-in shopper whose payment is declined by Payment_Gateway
WHEN: the shopper attempts checkout
THEN: no order exists, the cart remains unchanged, and the shopper sees a message indicating the payment was declined

AC: CHK-AC-003
GIVEN: a signed-in shopper whose account has insufficient funds at Payment_Gateway
WHEN: the shopper attempts checkout
THEN: no order exists, the cart remains unchanged, and the shopper sees a message indicating insufficient funds

ERROR: CHK-ERR-001
WHEN: Payment_Gateway returns PAYMENT_DECLINED for the payment_intent
THEN: reject the checkout, do not create an order, and notify the shopper that the charge was declined
ERROR_CODE: PAYMENT_DECLINED

ERROR: CHK-ERR-002
WHEN: Payment_Gateway returns INSUFFICIENT_FUNDS for the payment_intent
THEN: reject the checkout, do not create an order, and notify the shopper of insufficient funds
ERROR_CODE: INSUFFICIENT_FUNDS
