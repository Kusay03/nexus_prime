# Project Nexus — Presentation
## A Domain-Agnostic Entity-Relationship Platform

---

## 1. The Problem

Every organization manages **relational data** — people, assets, events, transactions — connected in complex ways.

Examples:
- **Cybersecurity:** attackers, servers, vulnerabilities, access logs
- **Supply chain:** suppliers, products, warehouses, shipments
- **Healthcare:** patients, doctors, prescriptions, diagnoses
- **Finance:** accounts, transactions, beneficiaries, risk flags

The traditional approach: **design a new database schema for every domain.**
New entity? New table. New relationship? New foreign key. New migration. New code.

**This doesn't scale** when the domain changes frequently or when you need to support multiple domains in the same system.

---

## 2. The Idea

**What if the schema itself was data?**

Instead of creating a table for each entity type (Users, Servers, Products...), we store the **definition** of entity types as rows in a metadata table. Attributes are not columns — they're rows too.

This is the **Entity-Attribute-Value (EAV)** pattern:

| Concept | Traditional DB | Our Approach |
|---------|---------------|--------------|
| New entity type | `CREATE TABLE ...` | `INSERT INTO Entity_Types ...` |
| New attribute | `ALTER TABLE ADD COLUMN ...` | `INSERT INTO Attributes ...` |
| New relationship | New FK or join table | `INSERT INTO Connections ...` |

The result: **one generic schema that can model any domain at runtime, without migrations.**

---

## 3. The Schema

Six tables. That's all.

```
Companies          — Multi-tenant isolation (who owns the data)
Entity_Types       — What kinds of things exist (User, Server, Product...)
Attributes         — What properties each type has (name, data_type)
Entities           — Individual instances of a type
Values             — The actual data (string, numeric, or date per attribute)
Connections        — Relationships between any two entities
```

```sql
CREATE TABLE Companies (
    company_id   SERIAL PRIMARY KEY,
    company_name VARCHAR(255) NOT NULL
);

CREATE TABLE Entity_Types (
    type_id      SERIAL PRIMARY KEY,
    company_id   INT REFERENCES Companies(company_id) ON DELETE CASCADE,
    type_name    VARCHAR(100) NOT NULL
);

CREATE TABLE Attributes (
    attribute_id   SERIAL PRIMARY KEY,
    type_id        INT REFERENCES Entity_Types(type_id) ON DELETE CASCADE,
    attribute_name VARCHAR(100) NOT NULL,
    data_type      VARCHAR(50) CHECK (data_type IN ('STRING', 'NUMBER', 'DATE'))
);

CREATE TABLE Entities (
    entity_id  SERIAL PRIMARY KEY,
    type_id    INT REFERENCES Entity_Types(type_id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE Values (
    value_id      SERIAL PRIMARY KEY,
    entity_id     INT REFERENCES Entities(entity_id) ON DELETE CASCADE,
    attribute_id  INT REFERENCES Attributes(attribute_id) ON DELETE CASCADE,
    string_value  VARCHAR(500),
    numeric_value DECIMAL(15, 2),
    date_value    DATE
);

CREATE TABLE Connections (
    connection_id      SERIAL PRIMARY KEY,
    source_entity_id   INT REFERENCES Entities(entity_id) ON DELETE CASCADE,
    target_entity_id   INT REFERENCES Entities(entity_id) ON DELETE CASCADE,
    relationship_type  VARCHAR(100) NOT NULL
);
```

---

## 4. Proof of Concept: Cyber Threat Intelligence Domain

To prove the idea works, we model a cybersecurity scenario **without touching the schema** — only INSERT statements:

```sql
-- Step 1: Create a tenant
INSERT INTO Companies (company_name) VALUES ('CyberGuard Inc.');

-- Step 2: Define entity types (no CREATE TABLE needed!)
INSERT INTO Entity_Types (company_id, type_name) VALUES
  (1, 'User'), (1, 'Server');

-- Step 3: Define attributes for each type
INSERT INTO Attributes (type_id, attribute_name, data_type) VALUES
  (1, 'Username', 'STRING'),
  (1, 'Threat Level', 'NUMBER'),
  (2, 'IP Address', 'STRING'),
  (2, 'OS', 'STRING'),
  (2, 'Risk Score', 'NUMBER');

-- Step 4: Create entity instances
INSERT INTO Entities (type_id) VALUES
  (1), (1), (1), (1), (1),   -- 5 Users  (IDs 1-5)
  (2), (2), (2), (2), (2);   -- 5 Servers (IDs 6-10)

-- Step 5: Assign values
INSERT INTO Values (entity_id, attribute_id, string_value) VALUES
  (1, 1, 'hacker_99'), (2, 1, 'shadow_x'), (3, 1, 'admin_john'),
  (4, 1, 'recon_bot'), (5, 1, 'insider_k');

INSERT INTO Values (entity_id, attribute_id, numeric_value) VALUES
  (1, 2, 85.5), (2, 2, 92.0), (3, 2, 15.0),
  (4, 2, 78.0), (5, 2, 60.0);

INSERT INTO Values (entity_id, attribute_id, string_value) VALUES
  (6, 3, '192.168.0.1'), (7, 3, '10.0.0.5'), (8, 3, '172.16.0.10'),
  (9, 3, '192.168.1.50'), (10, 3, '10.0.0.99');

INSERT INTO Values (entity_id, attribute_id, string_value) VALUES
  (6, 4, 'Linux'), (7, 4, 'Windows'), (8, 4, 'Linux'),
  (9, 4, 'FreeBSD'), (10, 4, 'Windows');

INSERT INTO Values (entity_id, attribute_id, numeric_value) VALUES
  (6, 5, 70.0), (7, 5, 45.0), (8, 5, 90.0),
  (9, 5, 30.0), (10, 5, 85.0);

-- Step 6: Create connections (the graph edges)
INSERT INTO Connections (source_entity_id, target_entity_id, relationship_type) VALUES
  (1, 6, 'UNAUTHORIZED_ACCESS'),
  (1, 7, 'PORT_SCAN'),
  (2, 8, 'UNAUTHORIZED_ACCESS'),
  (2, 6, 'PORT_SCAN'),
  (3, 9, 'AUTHORIZED_LOGIN'),
  (4, 7, 'PORT_SCAN'),
  (4, 10, 'PORT_SCAN'),
  (5, 10, 'UNAUTHORIZED_ACCESS'),
  (6, 8, 'LATERAL_MOVEMENT'),
  (7, 10, 'LATERAL_MOVEMENT'),
  (1, 2, 'COLLABORATES_WITH'),
  (4, 5, 'COLLABORATES_WITH');
```

> We just modeled an entire cybersecurity domain — **zero schema changes, zero migrations.**
> Tomorrow we could model a hospital, a logistics network, or a social graph using the same 6 tables.

---

## 5. The 20 Queries

### A. Schema Exploration — "What can this database model?"

**Q1 — List all entity types for a company**
```sql
SELECT et.type_name, c.company_name
FROM Entity_Types et
JOIN Companies c ON et.company_id = c.company_id
WHERE c.company_name = 'CyberGuard Inc.';
```

**Q2 — List all attributes for a given entity type**
```sql
SELECT a.attribute_name, a.data_type
FROM Attributes a
JOIN Entity_Types et ON a.type_id = et.type_id
WHERE et.type_name = 'User';
```

**Q3 — Count entities per type**
```sql
SELECT et.type_name, COUNT(e.entity_id) AS entity_count
FROM Entity_Types et
LEFT JOIN Entities e ON et.type_id = e.type_id
GROUP BY et.type_name
ORDER BY entity_count DESC;
```

**Q4 — Find entity types with no instances**
```sql
SELECT et.type_name
FROM Entity_Types et
LEFT JOIN Entities e ON et.type_id = e.type_id
WHERE e.entity_id IS NULL;
```

---

### B. Data Retrieval — "What do we know about this entity?"

**Q5 — Full profile of a single entity**
```sql
SELECT a.attribute_name,
       COALESCE(v.string_value, v.numeric_value::TEXT, v.date_value::TEXT) AS value
FROM Values v
JOIN Attributes a ON v.attribute_id = a.attribute_id
WHERE v.entity_id = 1;
```

**Q6 — List all users with their usernames**
```sql
SELECT e.entity_id, v.string_value AS username
FROM Entities e
JOIN Entity_Types et ON e.type_id = et.type_id
JOIN Values v ON e.entity_id = v.entity_id
JOIN Attributes a ON v.attribute_id = a.attribute_id
WHERE et.type_name = 'User' AND a.attribute_name = 'Username';
```

**Q7 — Find high-threat users (threat level > 75)**
```sql
SELECT v_name.string_value AS username, v_threat.numeric_value AS threat_level
FROM Entities e
JOIN Entity_Types et ON e.type_id = et.type_id
JOIN Values v_name ON e.entity_id = v_name.entity_id
JOIN Attributes a_name ON v_name.attribute_id = a_name.attribute_id
    AND a_name.attribute_name = 'Username'
JOIN Values v_threat ON e.entity_id = v_threat.entity_id
JOIN Attributes a_threat ON v_threat.attribute_id = a_threat.attribute_id
    AND a_threat.attribute_name = 'Threat Level'
WHERE et.type_name = 'User' AND v_threat.numeric_value > 75
ORDER BY v_threat.numeric_value DESC;
```

**Q8 — List all servers with IP, OS, and risk score**
```sql
SELECT v_ip.string_value AS ip_address,
       v_os.string_value AS os,
       v_risk.numeric_value AS risk_score
FROM Entities e
JOIN Entity_Types et ON e.type_id = et.type_id
JOIN Values v_ip ON e.entity_id = v_ip.entity_id
    AND v_ip.attribute_id = (SELECT attribute_id FROM Attributes WHERE attribute_name = 'IP Address')
LEFT JOIN Values v_os ON e.entity_id = v_os.entity_id
    AND v_os.attribute_id = (SELECT attribute_id FROM Attributes WHERE attribute_name = 'OS')
LEFT JOIN Values v_risk ON e.entity_id = v_risk.entity_id
    AND v_risk.attribute_id = (SELECT attribute_id FROM Attributes WHERE attribute_name = 'Risk Score')
WHERE et.type_name = 'Server';
```

---

### C. Graph Traversal — "How are things connected?"

**Q9 — Show all connections as readable graph edges**
```sql
SELECT
    src_v.string_value AS source_label,
    c.relationship_type AS action,
    tgt_v.string_value AS target_label
FROM Connections c
JOIN Values src_v ON c.source_entity_id = src_v.entity_id
JOIN Attributes src_a ON src_v.attribute_id = src_a.attribute_id
    AND src_a.attribute_name IN ('Username', 'IP Address')
JOIN Values tgt_v ON c.target_entity_id = tgt_v.entity_id
JOIN Attributes tgt_a ON tgt_v.attribute_id = tgt_a.attribute_id
    AND tgt_a.attribute_name IN ('Username', 'IP Address');
```

**Q10 — Find all targets of a specific attacker**
```sql
SELECT v_target.string_value AS target_ip, c.relationship_type
FROM Connections c
JOIN Values v_src ON c.source_entity_id = v_src.entity_id
JOIN Attributes a_src ON v_src.attribute_id = a_src.attribute_id
    AND a_src.attribute_name = 'Username'
JOIN Values v_target ON c.target_entity_id = v_target.entity_id
JOIN Attributes a_tgt ON v_target.attribute_id = a_tgt.attribute_id
    AND a_tgt.attribute_name = 'IP Address'
WHERE v_src.string_value = 'hacker_99';
```

**Q11 — Find all attackers who accessed a specific server**
```sql
SELECT v_user.string_value AS attacker, c.relationship_type
FROM Connections c
JOIN Values v_user ON c.source_entity_id = v_user.entity_id
JOIN Attributes a_user ON v_user.attribute_id = a_user.attribute_id
    AND a_user.attribute_name = 'Username'
JOIN Values v_srv ON c.target_entity_id = v_srv.entity_id
JOIN Attributes a_srv ON v_srv.attribute_id = a_srv.attribute_id
    AND a_srv.attribute_name = 'IP Address'
WHERE v_srv.string_value = '192.168.0.1';
```

**Q12 — 2-hop attack path: attacker -> server -> lateral movement target**
```sql
SELECT
    v_user.string_value AS initial_attacker,
    v_srv1.string_value AS compromised_server,
    v_srv2.string_value AS lateral_target
FROM Connections c1
JOIN Connections c2 ON c1.target_entity_id = c2.source_entity_id
JOIN Values v_user ON c1.source_entity_id = v_user.entity_id
JOIN Attributes a_user ON v_user.attribute_id = a_user.attribute_id
    AND a_user.attribute_name = 'Username'
JOIN Values v_srv1 ON c1.target_entity_id = v_srv1.entity_id
JOIN Attributes a_s1 ON v_srv1.attribute_id = a_s1.attribute_id
    AND a_s1.attribute_name = 'IP Address'
JOIN Values v_srv2 ON c2.target_entity_id = v_srv2.entity_id
JOIN Attributes a_s2 ON v_srv2.attribute_id = a_s2.attribute_id
    AND a_s2.attribute_name = 'IP Address'
WHERE c1.relationship_type = 'UNAUTHORIZED_ACCESS'
  AND c2.relationship_type = 'LATERAL_MOVEMENT';
```

---

### D. Analytics — "What patterns emerge?"

**Q13 — Count connections per relationship type**
```sql
SELECT relationship_type, COUNT(*) AS total
FROM Connections
GROUP BY relationship_type
ORDER BY total DESC;
```

**Q14 — Most targeted servers (by incoming connections)**
```sql
SELECT v.string_value AS server_ip, COUNT(c.connection_id) AS attack_count
FROM Connections c
JOIN Values v ON c.target_entity_id = v.entity_id
JOIN Attributes a ON v.attribute_id = a.attribute_id
    AND a.attribute_name = 'IP Address'
GROUP BY v.string_value
ORDER BY attack_count DESC
LIMIT 5;
```

**Q15 — Most active attackers (by outgoing connections)**
```sql
SELECT v.string_value AS attacker, COUNT(c.connection_id) AS actions
FROM Connections c
JOIN Values v ON c.source_entity_id = v.entity_id
JOIN Attributes a ON v.attribute_id = a.attribute_id
    AND a.attribute_name = 'Username'
GROUP BY v.string_value
ORDER BY actions DESC
LIMIT 5;
```

**Q16 — Average threat level per relationship type**
```sql
SELECT c.relationship_type,
       ROUND(AVG(v_threat.numeric_value), 2) AS avg_threat
FROM Connections c
JOIN Values v_threat ON c.source_entity_id = v_threat.entity_id
JOIN Attributes a ON v_threat.attribute_id = a.attribute_id
    AND a.attribute_name = 'Threat Level'
GROUP BY c.relationship_type
ORDER BY avg_threat DESC;
```

---

### E. Data Quality — "Is our data complete?"

**Q17 — Find entities with missing attributes**
```sql
SELECT e.entity_id, et.type_name, a.attribute_name
FROM Entities e
JOIN Entity_Types et ON e.type_id = et.type_id
JOIN Attributes a ON a.type_id = et.type_id
LEFT JOIN Values v ON v.entity_id = e.entity_id AND v.attribute_id = a.attribute_id
WHERE v.value_id IS NULL;
```

**Q18 — Detect isolated entities (no connections)**
```sql
SELECT e.entity_id, et.type_name,
       COALESCE(v.string_value, v.numeric_value::TEXT) AS label
FROM Entities e
JOIN Entity_Types et ON e.type_id = et.type_id
LEFT JOIN Values v ON e.entity_id = v.entity_id
LEFT JOIN Connections c_out ON e.entity_id = c_out.source_entity_id
LEFT JOIN Connections c_in  ON e.entity_id = c_in.target_entity_id
WHERE c_out.connection_id IS NULL AND c_in.connection_id IS NULL;
```

---

### F. Reporting — "Give me a full picture"

**Q19 — Cross-company entity summary**
```sql
SELECT c.company_name,
       et.type_name,
       COUNT(e.entity_id) AS entity_count
FROM Companies c
JOIN Entity_Types et ON c.company_id = et.company_id
LEFT JOIN Entities e ON et.type_id = e.type_id
GROUP BY c.company_name, et.type_name
ORDER BY c.company_name, entity_count DESC;
```

**Q20 — Pivot query: reconstruct EAV data as a flat table**
```sql
SELECT e.entity_id,
       et.type_name,
       MAX(CASE WHEN a.attribute_name = 'Username'     THEN v.string_value END) AS username,
       MAX(CASE WHEN a.attribute_name = 'Threat Level' THEN v.numeric_value::TEXT END) AS threat_level,
       MAX(CASE WHEN a.attribute_name = 'IP Address'   THEN v.string_value END) AS ip_address,
       MAX(CASE WHEN a.attribute_name = 'OS'           THEN v.string_value END) AS os,
       MAX(CASE WHEN a.attribute_name = 'Risk Score'   THEN v.numeric_value::TEXT END) AS risk_score
FROM Entities e
JOIN Entity_Types et ON e.type_id = et.type_id
LEFT JOIN Values v ON e.entity_id = v.entity_id
LEFT JOIN Attributes a ON v.attribute_id = a.attribute_id
GROUP BY e.entity_id, et.type_name
ORDER BY et.type_name, e.entity_id;
```

---

## 6. Why This Matters

| Advantage | Explanation |
|-----------|-------------|
| **Domain-agnostic** | Same 6 tables work for cybersecurity, HR, logistics, healthcare... |
| **No migrations** | New entity types = INSERT, not ALTER TABLE |
| **Self-describing** | The database contains its own metadata — query Q1-Q2 to discover the schema |
| **Multi-tenant** | Companies table isolates data per organization |
| **Graph-ready** | Connections table naturally models directed graph edges |

| Known Limitation | Explanation |
|------------------|-------------|
| **Complex queries** | EAV requires many JOINs to reconstruct "rows" (see Q7, Q8, Q12) |
| **No native traversal** | Multi-hop queries get verbose — SQL isn't designed for graph walks |
| **Scalability** | Self-joins on Values table can degrade with millions of rows |

> These limitations point toward a natural evolution: migrating to a **native graph database** for traversal-heavy workloads.
