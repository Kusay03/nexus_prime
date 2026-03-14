// ============================================================
// Project Nexus — Neo4j bootstrap
// Run once after container starts:
//   cypher-shell -u $NEO4J_USER -p $NEO4J_PASSWORD -f neo4j/init.cypher
// ============================================================

// --- Uniqueness constraints ---

// Entity instances are globally unique by UUID
CREATE CONSTRAINT entity_id_unique IF NOT EXISTS
FOR (e:Entity) REQUIRE e.id IS UNIQUE;

// --- Indexes for ontology lookups (always scoped to tenant_id) ---

// EntityType lookup by (tenant_id, name) — used on every MERGE/MATCH
CREATE INDEX entitytype_tenant_name IF NOT EXISTS
FOR (et:EntityType) ON (et.tenant_id, et.name);

// Attribute lookup — scoped per tenant
CREATE INDEX attribute_tenant_name IF NOT EXISTS
FOR (a:Attribute) ON (a.tenant_id, a.name);

// RelationshipType lookup by (tenant_id, name)
CREATE INDEX reltype_tenant_name IF NOT EXISTS
FOR (rt:RelationshipType) ON (rt.tenant_id, rt.name);

// Entity listing and filtering by tenant
CREATE INDEX entity_tenant IF NOT EXISTS
FOR (e:Entity) ON (e.tenant_id);

// Entity lookup by (tenant_id, type) for filtered graph queries
CREATE INDEX entity_tenant_type IF NOT EXISTS
FOR (e:Entity) ON (e.tenant_id, e.type_name);

// --- User constraints (Phase 3 — Auth) ---

// user_id is the primary key (UUID, globally unique)
CREATE CONSTRAINT user_id_unique IF NOT EXISTS
FOR (u:User) REQUIRE u.user_id IS UNIQUE;

// Usernames are globally unique across all tenants
CREATE CONSTRAINT user_username_unique IF NOT EXISTS
FOR (u:User) REQUIRE u.username IS UNIQUE;

// Lookup users by tenant (admin listing, RBAC checks)
CREATE INDEX user_tenant IF NOT EXISTS
FOR (u:User) ON (u.tenant_id);
