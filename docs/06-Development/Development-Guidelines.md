# Dolphin Flow - Development Guidelines

Version:
0.1

Status:
Development Standard

Last Updated:
2026-08-05


# 1. Purpose

This document defines development standards and practices for Dolphin Flow.

The purpose is to ensure:

- Consistent code quality
- Maintainable architecture
- Easier collaboration
- Reduced technical debt


# 2. Development Principles


## DEV-001 Clean Code

Code should be:

- Readable
- Understandable
- Maintainable


Complex logic should be documented.


## DEV-002 Separation of Responsibilities

Each layer should have a clear responsibility.


Example:


~~~text
API Layer

Handles:

- Requests
- Responses


Service Layer

Handles:

- Business logic


Model Layer

Handles:

- Data structure
~~~


## DEV-003 Avoid Duplication

Common logic should be implemented once and reused.


# 3. Backend Development Standards


## 3.1 Django Application Structure


Each Django application should follow a modular structure.


Recommended:


~~~text
app_name/

├── models.py

├── views.py

├── serializers.py

├── services/

├── permissions/

├── tests/

└── urls.py
~~~


# 3.2 Business Logic Location


Business logic should be placed inside service classes.


Avoid:


~~~python
def view_function():
    calculate_price()
    send_notification()
    update_status()
~~~


Preferred:


~~~python
repair_service.complete_repair()
~~~


# 4. Naming Conventions


## Python


Use:

- snake_case


Example:


~~~python
repair_request
customer_address
~~~


## Classes


Use:

- PascalCase


Example:


~~~python
RepairRequest
WorkflowInstance
~~~


## Constants


Use:

- UPPER_CASE


Example:


~~~python
MAX_UPLOAD_SIZE
~~~


# 5. Database Development Rules


## 5.1 Migration Control


All database changes must be performed through Django migrations.


Direct production database changes are prohibited.


## 5.2 Model Design


Models should:


- Have meaningful names
- Include timestamps
- Define relationships clearly


Example:


~~~text
created_at

updated_at
~~~


# 6. API Development Standards


APIs should follow:


- REST principles
- Versioning
- Consistent responses


Example:


~~~text
/api/v1/repair/requests/

/api/v1/devices/
~~~


# 7. Error Handling


Errors should provide:


- Clear message
- Error code
- Suggested action


Example:


~~~json
{
 "error": "DEVICE_NOT_FOUND",
 "message": "Device with this IMEI does not exist"
}
~~~


# 8. Frontend Development Standards


Frontend code should follow:


- Component-based design
- Reusable components
- Clear separation of logic and UI


Example:


~~~text
Component

|

Business Hook

|

API Service

|

Backend API
~~~


# 9. Git Workflow


Git is the source of truth for project changes.


Repository branches:


~~~text
main

Production-ready code


develop

Integration branch


feature/*

New features


bugfix/*

Bug fixes
~~~


# 10. Commit Standards


Commit messages should be meaningful.


Format:


~~~text
type: description
~~~


Examples:


~~~text
feat: add repair workflow model

fix: resolve notification issue

docs: update architecture document
~~~


# 11. Code Review Rules


Before merging:


- Code should be reviewed
- Tests should pass
- Documentation should be updated if required


# 12. Testing Standards


The system should include:


## Unit Tests

For:

- Services
- Business rules


## Integration Tests

For:

- APIs
- Workflow execution


## User Acceptance Tests

For:

- Business processes


# 13. Documentation Rules


Every major change should update:


- Architecture documents
- Decision logs
- API documentation
- User documentation


# 14. Environment Management


Development environments should be separated:


~~~text
Development

Testing

Production
~~~


Configuration should not be stored in source code.


Example:


~~~text
Environment Variables

Database Password

Secret Keys

API Keys
~~~


# 15. Security Development Rules


Developers must consider:


- Input validation
- Permission checks
- Secure file handling
- Audit requirements


# 16. Performance Considerations


Developers should consider:


- Database query optimization
- Pagination
- Background tasks
- Caching when needed


# 17. Deployment Considerations


Production deployment should support:


- Version tracking
- Rollback capability
- Backup verification


# 18. Related Documents


Backend Architecture:

~~~text
docs/03-Architecture/Backend-Architecture.md
~~~


Security Architecture:

~~~text
docs/03-Architecture/Security-Architecture.md
~~~


Decision Log:

~~~text
docs/01-Project/Decision-Log.md
~~~