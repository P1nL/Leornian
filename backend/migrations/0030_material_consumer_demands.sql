CREATE UNIQUE INDEX material_demands_consumer
    ON knowledge.material_demands(actor_id, consumer_ref);
