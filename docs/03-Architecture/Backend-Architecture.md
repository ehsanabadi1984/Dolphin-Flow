# Dolphin Flow - Backend Architecture

Version:
0.1

Status:
Architecture & Planning

Last Updated:
2026-08-05


# 1. Purpose

This document defines the backend architecture of Dolphin Flow.

It describes the Django application structure, module boundaries, internal communication patterns, and backend development principles.


# 2. Backend Technology Stack


## Framework

Django


## API Framework

Django REST Framework


## Database

PostgreSQL


## Background Processing

Recommended:

Celery + Redis


Purpose:

- Scheduled tasks
- SLA monitoring
- Notifications
- Background jobs


## File Storage

Initial:

Local storage

Future:

Object storage compatible with S3 API


---

# 3. Backend Architecture Style


The backend follows:

Modular Monolith Architecture


The Django project consists of independent applications grouped into:

Dolphin Flow Backend
├── Core Applications
│
├── Workflow Applications
│
└── Business Applications

---


Each module owns its:

- Models
- Business logic
- Services
- APIs
- Permissions


---

# 4. Django Project Structure


Recommended structure:

backend/

├── config/
│ ├── settings/
│ ├── urls.py
│ └── wsgi.py
│
├── apps/
│
│ ├── accounts/
│ ├── permissions/
│ ├── audit/
│ ├── workflow/
│ ├── sla/
│ ├── notifications/
│ ├── documents/
│ │
│ ├── repair/
│ ├── inventory/
│ └── finance/
│
├── common/
│
├── requirements/
│
└── manage.py



---

# 5. Core Applications


Core applications provide shared platform capabilities.


## Accounts

Responsibilities:

- Users
- Authentication
- User profiles


## Permissions

Responsibilities:

- Roles
- Permissions
- Access control


## Audit

Responsibilities:

- Activity tracking
- History
- Change tracking


## Workflow

Responsibilities:

- Workflow definitions
- Stages
- Tasks
- Transitions


## SLA

Responsibilities:

- SLA rules
- Timers
- Escalations


## Notifications

Responsibilities:

- Internal notifications
- SMS
- Email


## Documents

Responsibilities:

- File management
- Document relationships


---

# 6. Business Applications


Business applications contain organizational processes.


## Repair Module


Responsibilities:

- Repair requests
- Devices
- Warranty
- Repair operations


## Inventory Module


Responsibilities:

- Warehouse operations
- Device movement
- Receipts


## Finance Module


Responsibilities:

- Cost management
- Payment verification
- Financial documents


---

# 7. Application Communication Rules


Modules should communicate through:


## Services

Example:

Repair Module
|
Workflow Service
|
Notification Service



Direct database access between modules is discouraged.


Example:


Incorrect:
Repair
|
|
Directly modify Notification tables


Correct:

Repair

|

Notification Service

|

Notification Module



---

# 8. Business Logic Layer


Business logic should not be placed inside:

- Views
- API Controllers
- Models only


Recommended structure:

app/

├── models.py

├── services/

│ ├── repair_service.py
│ ├── workflow_service.py
│ └── notification_service.py

├── api/

│ ├── serializers.py
│ └── views.py



---

# 9. Workflow Integration


Business modules should use Workflow Engine.


Example:


Repair Process:



Repair Request Created

    |

Workflow Instance Created

    |

Stage Tasks Generated

    |

Users Complete Tasks

    |

Process History Updated



---

# 10. Audit Integration


Every important operation should generate audit records.


Examples:


- Creating repair request
- Warranty approval
- Cost approval
- Warehouse receipt
- Financial confirmation


---

# 11. Security Considerations


Backend must support:


## Authentication

User identity verification.


## Authorization

Permission checking.


## Object-Level Security

Users should only access allowed records.


## Audit Logging

Sensitive operations must be recorded.


---

# 12. API Architecture


API style:


REST API


Main principles:


- Resource-oriented endpoints
- Versioned APIs
- Clear error responses


Example:

/api/v1/repair/requests/

/api/v1/devices/

/api/v1/workflows/



---

# 13. Future Evolution


The backend architecture allows:


- Adding new business modules
- External API integrations
- AI services
- Mobile applications


Possible future separation:
Modular Monolith
|
Selected Modules
|
Independent Services


---

# 14. Related Documents


System Architecture:
docs/03-Architecture/System-Architecture.md

Frontend Architecture:
docs/03-Architecture/Frontend-Architecture.md

Database Architecture:
docs/03-Architecture/Database-Architecture.md
