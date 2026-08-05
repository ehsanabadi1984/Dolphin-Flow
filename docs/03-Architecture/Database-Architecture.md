# Dolphin Flow - Database Architecture

Version:
0.1

Status:
Architecture & Planning

Last Updated:
2026-08-05


# 1. Purpose

This document defines the database architecture of Dolphin Flow.

It describes the database design principles, data organization strategy, core entities, and relationships between major system components.


# 2. Database Technology


Primary Database:

PostgreSQL


Reasoning:

PostgreSQL is selected because the system requires:

- Complex relational data
- Strong transaction consistency
- Audit history
- Workflow relationships
- Reporting capabilities
- Future scalability


# 3. Database Design Principles


## 3.1 Data Integrity

The database must ensure:

- Valid relationships
- Transaction consistency
- Controlled updates


## 3.2 Historical Data Preservation

Important business history must never be overwritten.

The system should preserve:

- Previous values
- Status changes
- Approvals
- User actions


## 3.3 Separation of Concerns

Database structure should separate:


Core Platform Data

from

Business Module Data


## 3.4 Auditability

Important entities must support tracking:

- Creation
- Modification
- Ownership
- Status changes


# 4. Database Logical Structure


The database is divided into:

Database

├── Identity Domain
│
├── Workflow Domain
│
├── Audit Domain
│
├── Document Domain
│
├── Notification Domain
│
└── Business Domains
├── Repair
├── Inventory
└── Finance


# 5. Core Platform Entities


# 5.1 User Entity


Purpose:

Stores system users.


Main attributes:


- User identity
- Authentication information
- Department
- Status


Related entities:

- Roles
- Permissions
- Audit Logs


---

# 5.2 Role Entity


Purpose:

Defines user responsibilities.


Examples:

- Administrator
- Support
- Repair Technician
- Warehouse Staff
- Finance


Relationships:

User

|

Role

|

Permission


---

# 5.3 Workflow Entity


Purpose:

Stores workflow definitions.


Examples:

- Repair Workflow
- Approval Workflow


Contains:

- Workflow name
- Stages
- Rules
- Version


---

# 5.4 Workflow Instance Entity


Purpose:

Stores running processes.


Example:

A repair request creates a workflow instance.


Contains:

- Current stage
- Status
- Start time
- Completion time


---

# 5.5 Task Entity


Purpose:

Represents user actions inside workflows.


Contains:

- Assigned user
- Assigned department
- Status
- Due date


---

# 5.6 SLA Entity


Purpose:

Stores service level rules.


Contains:

- Allowed duration
- Warning threshold
- Escalation rules


---

# 5.7 Audit Log Entity


Purpose:

Stores system history.


Contains:


- User
- Action
- Object
- Previous value
- New value
- Timestamp


# 5.8 Document Entity


Purpose:

Manages uploaded files.


Contains:

- File information
- Owner
- Related object
- Upload details


# 6. Repair Domain Entities


# 6.1 Customer


Stores customer information.


Attributes:


- Name
- Contact information
- Address


---

# 6.2 Repair Request


Represents a repair case.


Attributes:


- Request number
- Customer
- Creation date
- Status
- Workflow reference


---

# 6.3 Device


Represents a physical device.


Primary identifier:


IMEI


Attributes:


- Device type
- Serial number
- Model


Important rule:

One device can have multiple repair requests over time.


Relationship:

Device

|

Repair Request

|

Repair History


---

# 6.4 Repair Operation


Stores technical repair activities.


Contains:

- Technician
- Diagnosis
- Actions performed
- Result


---

# 7. Inventory Domain Entities


Main entities:


## Warehouse


Stores warehouse information.


## Inventory Transaction


Tracks device movement.


Examples:

- Receive
- Transfer
- Deliver


## Warehouse Document


Stores:

- Receipt
- Transfer document
- Delivery record


# 8. Finance Domain Entities


Main entities:


## Repair Cost


Stores estimated and final costs.


## Payment Record


Stores customer payments.


## Financial Approval


Stores finance confirmation.


# 9. Relationship Overview


High-level relationship:

Customer

|

Repair Request

|

Device

|

Workflow Instance

|

Tasks

|

Approvals

|

Documents

|

Audit Logs



# 10. Database Security


Database access must follow:


- Least privilege principle
- Application-level access control
- Controlled migrations
- Regular backups


# 11. Backup and Recovery


Database strategy should support:


- Scheduled backups
- Point-in-time recovery
- Backup verification


# 12. Performance Considerations


The database design should consider:


- Proper indexing
- Query optimization
- Pagination
- Reporting performance


# 13. Future Expansion


The database architecture should support:


- Customer portal
- AI analysis data
- Advanced analytics
- External integrations


# 14. Related Documents


System Architecture:
docs/03-Architecture/System-Architecture.md

Backend Architecture:
docs/03-Architecture/Backend-Architecture.md

Security Architecture:
docs/03-Architecture/Security-Architecture.md