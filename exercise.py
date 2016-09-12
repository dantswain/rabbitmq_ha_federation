import pika
import sys
import time

assert len(sys.argv) == 3, "Usage: exercise.py rabbit1 rabbit2"
node1 = "amqp://guest:guest@%s" % sys.argv[1]
node2 = "amqp://guest:guest@%s" % sys.argv[2]

print "cluster 1 url: %s" % node1
print "cluster 2 url: %s" % node2

def declare_exchange(url, exchange):
    connection = pika.BlockingConnection(pika.URLParameters(url))
    channel = connection.channel()

    channel.exchange_declare(exchange=exchange, type='fanout', durable=True)

    connection.close()
    return True

def declare_exchange_queue(url, queue, exchange):
    connection = pika.BlockingConnection(pika.URLParameters(url))
    channel = connection.channel()

    channel.exchange_declare(exchange=exchange, type='fanout', durable=True)
    channel.queue_declare(queue=queue, durable=False)
    channel.queue_bind(exchange=exchange, queue=queue)

    connection.close()
    return True

def publish_message(url, exchange, payload):
    connection = pika.BlockingConnection(pika.URLParameters(url))
    channel = connection.channel()

    channel.exchange_declare(exchange=exchange, type='fanout', durable=True)
    channel.basic_publish(exchange=exchange,
                          routing_key='na',
                          body=payload)

    connection.close()
    return True

def confirm_delivery(url, queue, expected_payload):
    connection = pika.BlockingConnection(pika.URLParameters(url))
    channel = connection.channel()

    mf, hf, got_payload = channel.basic_get(queue)
    if mf:
        assert expected_payload == got_payload, "Payload mismatch %s != %s" % (expected_payload, got_payload)
        channel.basic_ack(mf.delivery_tag)
    else:
        assert False, "Failed to get payload on %s" % url

    connection.close()
    return True

print("Declaring exchange federated.stuff")
declare_exchange(node1, "federated.stuff")
# we don't have to do this, but this way we don't have to wait
declare_exchange(node2, "federated.stuff")

print("Declaring queue stuff.cluster1 on cluster 1")
declare_exchange_queue(node1, "stuff.cluster1", "federated.stuff")

print("Declaring queue stuff.cluster2 on cluster 2")
declare_exchange_queue(node2, "stuff.cluster2", "federated.stuff")

payload = "payload test %s" % time.strftime("%c")
publish_message(node1, "federated.stuff", payload)
confirm_delivery(node1, "stuff.cluster1", payload)
confirm_delivery(node2, "stuff.cluster2", payload)

print("Success!")
