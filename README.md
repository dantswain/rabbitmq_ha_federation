# RabbitMQ Federation + HA Upstream Queues Proof of Concept

This repository contains code and config to explore using RabbitMQ
[Federation](https://www.rabbitmq.com/federation.html) combined with
[highly available (HA) queues](https://www.rabbitmq.com/ha.html) to
achieve HA federation between clusters.

## Background

### Federated clusters and durable upstream exchanges

When you want a message to transit from one node / cluster to another
node / cluster using federation, the FROM node / cluster is called the
UPSTREAM and the TO node / cluster is called the DOWNSTREAM.

The federation plugin provides a mechanism to specify an upstream
cluster.  This can be achieved by supplying a list of upstream uris in
the config payload when calling `set_parameter federation-upstream`, e.g.,

```json
{
  "uri": [
      "amqp://guest:guest@rabbit1",
      "amqp://guest:guest@rabbit2"
  ]
}
```

When connecting to an upstream cluster, the federation plugin will
attempt to connect to the upstream uris in random order until a
connection is established.

When federating an exchange, RabbitMQ creates a queue on an upstream
node for messages that are to be delivered to the downstream
exchange.  This queue is called the "upstream queue" and usually has a
named like `federation: federated.stuff -> rabbit@rabbit3`.  Upstream
queues are declared as durable (they survive node restarts) and their
home node is whichever upstream node to which the federation plugin is
connected.

Upon failure of an upstream node which is the home node for an
upstream queue, the federation link for the corresponding exchange
will fail to connect because the upstream queue is unavailable.  I
cannot speak for the RabbitMQ developers, but I suspect that this
design favors at-most-once and in-order delivery.  That is, any
messages held by the upstream queue at the time of node failure can
not be delivered until that node recovers.  If the queue were not
durable, we may have a situation where messages are delivered multiple
times and/or out of order once the original node recovers. See
[https://github.com/rabbitmq/rabbitmq-federation/issues/4](https://github.com/rabbitmq/rabbitmq-federation/issues/4)
for discussion.

There are use cases where we would like to favor availability of a
federated exchange over delivery guarantees.  For example, we may be
streaming a large volume of messages across data centers and we would
rather not stop the stream for any extended periods of time even if
that comes with the potential for occasional lost, out-of-order, or
duplicated messages.  That is, we may favor high availability over
consistency of delivery (yay, CAP theorem!). 

### HA upstream queues

One solution to provide HA federation is to apply an
[HA queue policy](https://www.rabbitmq.com/ha.html) to upstream
queues.  We can do this by applying the policy to any queues that
matchin the pattern `^federation:*` because upstream queue names start
with `federation:`:

```
rabbitmqctl set_policy ha-federation "^federation:*" '{"ha-mode": "all"}'
```

This will configure the cluster to apply an HA policy to upstream
queues that mirrors those queues across all nodes in the cluster.
With this setup, when an upstream node fails that owns an upstream
queue, the downstream can reconnect to another upstream node and
utilize the mirrored upstream queue.

### Performance Impact

TODO.  Not sure how queue mirroring impacts throughput.  I suspect the
bottleneck is trans-datacenter communication, not trans-node within
the same datacenter.

## Experimenting

Prerequisites: You must have docker installed and running as well as
docker-compose installed.

Clone the repo, launch the containers, and set up the clusters:

```
git clone https://github.com/dantswain/rabbitmq_ha_federation
docker-compose up -d
./setup_cluster.sh
```

This sets up two RabbitMQ clusters: one with nodes `rabbit1` and
`rabbit2` and one with nodes `rabbit3` and `rabbit4`.  The federation
plugin is installed on both clusters and they are configured so that
any exchange matching the name `federated.*` is federated across both
clusters.  Federation upstream queues are configured with HA
mirroring to all other nodes in the cluster.

If you are running Mac OS X, you can open the admin pages for all four
nodes by running `./open_admins.sh`.  The username and password are
both 'guest' for all four nodes.

Execute a test under the fully connected (no nodes down) scenario:

```
docker-compose run --rm admin python /exercise.py rabbit1 rabbit3
```

The two arguments (`rabbit1` and `rabbit3`) are which node to use for
the test.  A message is published to the first node and then we verify
that it is received on the second node.  The first node should be on
the first cluster and the second node should be on the second cluster.

Now bring one node down.  For an effective test, choose the node that
hosts the upstream queue on the first cluster (since we will publish
to the first cluster and we want to make sure the message still
arrives at the second cluster).  To determine which node to bring down,
either look in the admin page for node 1 or 2 or run the command below
and look for the `node` parameter of the `federation: federated.stuff
-> rabbit@<either rabbit3 or rabbit4>` queue.

```
docker-compose run --rm admin rabbitmqadmin -H rabbit1 -f long -d 3 list queues
```

Assuming that the host node is rabbit2 (`rabbit@rabbit2` shows up in
the node parameter of the detailed list of queues for the upstream
queue), shut down node 2:

```
docker-compose exec rabbit2 rabbitmqctl stop_app
```

You may want to wait a few moments to make sure the federation plugin
reconnnects.  You can monitor this via the "Admin" panel of the
management webpage for node 3 or 4, under the "Federation Status"
page.  It should show "running" as the state for cluster1 and it will
be connected via uri `amqp://rabbit1` (or rabbit2 if we stopped rabbit1).

Now run the test, supplying rabbit1 and rabbit3 as the arguments:

```
docker-compose run --rm admin python /exercise.py rabbit1 rabbit3
cluster 1 url: amqp://guest:guest@rabbit1
cluster 2 url: amqp://guest:guest@rabbit3
Declaring exchange federated.stuff
Declaring queue stuff.cluster1 on cluster 1
Declaring queue stuff.cluster2 on cluster 2
Success!
```

We can re-enable rabbit2 and repeat the test:

```
docker-compose exec rabbit2 rabbitmqctl start_app
```

Then

```
docker-compose run --rm admin python /exercise.py rabbit1 rabbit3
cluster 1 url: amqp://guest:guest@rabbit1
cluster 2 url: amqp://guest:guest@rabbit3
Declaring exchange federated.stuff
Declaring queue stuff.cluster1 on cluster 1
Declaring queue stuff.cluster2 on cluster 2
Success!
```

We should now be able to shut down node rabbit1 and repeat the
experiment, this time using rabbit2 for the test.
```
docker-compose exec rabbit1 rabbitmqctl stop_app
```

You may have to wait a bit for the federation link to re-establish
after taking down rabbit1 (on the order of, say, 60 seconds - use the
admin page to monitor - the connections are tried randomly so it may
take a few iterations to succeed).

```
docker-compose run --rm admin python /exercise.py rabbit2 rabbit3
cluster 1 url: amqp://guest:guest@rabbit2
cluster 2 url: amqp://guest:guest@rabbit3
Declaring exchange federated.stuff
Declaring queue stuff.cluster1 on cluster 1
Declaring queue stuff.cluster2 on cluster 2
Success!
```

Then bring rabbit1 back up

```
docker-compose exec rabbit1 rabbitmqctl start_app
```

### Don't panic

If the clusters get into a bad state, you can always reset the whole
thing by running

```
docker-compose down
```

and then restarting everything (`docker-compose up -d` and
`./setup_cluster.sh`).
