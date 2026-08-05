# Dolphin Flow - User Roles & Permissions

Version:
0.1

Status:
Analysis & Documentation

Last Updated:
2026-08-05


# 1. Purpose

This document defines user roles, responsibilities, and access boundaries in Dolphin Flow.

The permission model is based on:

- Role Based Access Control (RBAC)
- Department ownership
- Workflow responsibilities


# 2. Access Control Principles


## Principle 1

Users can only access information required for their responsibilities.


## Principle 2

Permissions are assigned to roles, not directly to individual users.


## Principle 3

Sensitive actions require higher authorization levels.


## Principle 4

All permission-based actions must be audited.


---

# 3. Organizational Roles


# ROLE-001 System Administrator


## Description

Technical administrator responsible for system configuration.


## Department

IT


## Permissions


Users:

- Create users
- Disable users
- Manage profiles


Roles:

- Create roles
- Assign permissions


System:

- Configure settings
- Manage integrations
- View system logs


Restrictions:

System administrators should not modify business records unless explicitly authorized.


---

# ROLE-002 Administrative Staff


## Description

Responsible for device reception and final customer shipment.


## Main Responsibilities

- Receive devices
- Create repair requests
- Register customer information
- Confirm shipping details


## Permissions


Repair:

- Create repair request
- View assigned requests
- Update administrative information


Shipping:

- Register shipment information
- Upload shipping documents


Restrictions:

Cannot modify technical or financial information.


---

# ROLE-003 Support Staff


## Description

Responsible for customer communication and warranty evaluation.


## Main Responsibilities

- Warranty evaluation
- Cost estimation
- Customer approval management


## Permissions


Repair:

- View repair requests
- Update warranty status
- Register estimated costs


Customer:

- Record customer communication
- Send notifications


Restrictions:

Cannot modify repair technical reports.


---

# ROLE-004 Repair Technician


## Description

Responsible for technical inspection and repair operations.


## Main Responsibilities

- Device diagnosis
- Repair execution
- Technical reporting


## Permissions


Repair:

- Receive assigned devices
- Update repair status
- Add technical reports
- Record repair actions


Documents:

- Upload technical documents


Restrictions:

Cannot approve financial operations.


---

# ROLE-005 Warehouse Staff


## Description

Responsible for device storage and movement.


## Main Responsibilities

- Receive devices
- Store devices
- Transfer devices


## Permissions


Inventory:

- Create warehouse receipt
- Create warehouse transfer
- Update warehouse status


Documents:

- Upload warehouse documents


Restrictions:

Cannot modify repair or financial decisions.


---

# ROLE-006 Finance Staff


## Description

Responsible for payment verification and financial approval.


## Main Responsibilities

- Verify payments
- Approve financial documents


## Permissions


Finance:

- Register payment information
- Upload financial documents
- Approve payment status


Restrictions:

Cannot modify technical workflow stages.


---

# ROLE-007 Department Manager


## Description

Manager responsible for department supervision.


## Permissions


Monitoring:

- View department processes
- View SLA status
- View reports


Approval:

- Approve exceptions
- Approve overrides (if authorized)


---

# ROLE-008 System Manager


## Description

Business-level administrator.


## Permissions


Workflow:

- Manage workflow definitions
- Configure SLA policies


Security:

- Manage advanced permissions


Reports:

- Access organization-wide reports


---

# 4. Role Permission Matrix


| Capability | Admin | Support | Repair | Warehouse | Finance | Manager |
|---|---|---|---|---|---|---|
| Create Request | ✓ | - | - | - | - | - |
| Warranty Check | - | ✓ | - | - | - | ✓ |
| Repair Update | - | - | ✓ | - | - | View |
| Upload Documents | ✓ | ✓ | ✓ | ✓ | ✓ | View |
| Financial Approval | - | - | - | - | ✓ | ✓ |
| Warehouse Receipt | - | - | - | ✓ | - | View |
| Reports | Limited | Limited | Limited | Limited | Limited | ✓ |


---

# 5. Workflow Responsibility Mapping


| Workflow Stage | Responsible Role |
|---|---|
| Device Reception | Administrative Staff |
| Warranty Evaluation | Support Staff |
| Cost Approval | Support Staff |
| Repair Execution | Repair Technician |
| Financial Verification | Finance Staff |
| Warehouse Processing | Warehouse Staff |
| Final Shipping | Administrative Staff |


---

# 6. Future Roles


Possible future roles:


## Customer

Customer portal access.


## Quality Inspector

Quality control workflows.


## Executive Viewer

Read-only organizational dashboard.


---

# 7. Implementation Notes


The permission system should support:


- Role inheritance
- Department-based filtering
- Object-level permissions
- Workflow-based permissions


Implementation should avoid hard-coded permissions.