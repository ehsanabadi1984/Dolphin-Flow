# Dolphin Flow - Coding Standards

Version:
0.1

Status:
Development Standard

Last Updated:
2026-08-05


# 1. Purpose

This document defines coding standards for Dolphin Flow development.

The purpose is to maintain:

- Clean code
- Consistent implementation
- Easier maintenance
- Better collaboration


# 2. General Coding Principles


## 2.1 Readability First

Code should be written for humans first and machines second.


Developers should prefer:

- Clear names
- Simple logic
- Small functions


## 2.2 Single Responsibility

Each component should have one clear responsibility.


Example:


~~~text
Notification Service

Responsible for:

Sending notifications


Not responsible for:

Calculating repair cost
~~~


## 2.3 Avoid Premature Optimization

Performance improvements should be based on real requirements and measurements.


# 3. Backend Coding Standards


## 3.1 Python Style


The backend follows Python standard conventions.


Rules:


- Use meaningful names
- Avoid unnecessary complexity
- Follow PEP 8 principles


# 3.2 Naming Convention


## Variables and Functions


Use:

~~~python
repair_request
calculate_sla_time
~~~


## Classes


Use:

~~~python
RepairRequest
WorkflowEngine
~~~


## Constants


Use:

~~~python
DEFAULT_TIMEOUT
MAX_FILE_SIZE
~~~


# 4. Django Application Standards


Each application should have a clear responsibility.


Example:


~~~text
repair/

Handles:

- Repair requests
- Device repair logic
- Repair history


notification/

Handles:

- SMS
- Email
- Internal alerts
~~~


# 5. Model Standards


Django models should:


- Represent business entities clearly
- Avoid storing complex business logic
- Include required metadata


Recommended fields:


~~~python
created_at

updated_at

created_by

updated_by
~~~


# 6. Service Layer Standards


Business logic should be implemented in services.


Example:


Preferred:


~~~python
repair_service.complete_repair()
~~~


Avoid:


~~~python
view.complete_repair()
~~~


# 7. API Standards


API endpoints should:


- Be predictable
- Use versioning
- Return consistent responses


Example:


~~~text
/api/v1/repair/requests/

/api/v1/workflows/
~~~


# 8. Frontend Coding Standards


Frontend development should follow:


- Component-based architecture
- Reusable components
- Clear separation of UI and logic


Example:


~~~text
Component

      |

Logic Hook

      |

API Service

      |

Backend API
~~~


# 9. Component Rules


Components should:


- Have a clear purpose
- Avoid excessive size
- Be reusable when possible


Avoid:


~~~text
One huge component containing:

- UI
- API calls
- Business rules
- Validation
~~~


# 10. Error Handling Standards


Errors should be:


- Meaningful
- Understandable
- Logged when required


Example:


Bad:


~~~text
Something went wrong
~~~


Better:


~~~text
Payment confirmation failed because the transaction ID is missing.
~~~


# 11. Logging Standards


Important operations should generate logs.


Examples:


- Authentication events
- Workflow changes
- Approval actions
- Errors


# 12. Testing Standards


Code should include appropriate tests.


Required areas:


## Unit Tests


For:


- Business logic
- Services
- Rules


## Integration Tests


For:


- API endpoints
- Workflow execution


## Critical Business Tests


For:


- Repair process
- Approval process
- Financial confirmation


# 13. Code Documentation


Complex logic should include documentation.


Documentation should explain:


- Why this approach was chosen
- Important business rules
- Possible limitations


# 14. Security Coding Rules


Developers must consider:


- Input validation
- Permission checks
- Secure file handling
- Sensitive data protection


# 15. Database Coding Rules


Rules:


- Use migrations
- Avoid direct production changes
- Optimize queries
- Prevent unnecessary database calls


# 16. Git Commit Standards


Commit messages should follow:


~~~text
type: description
~~~


Examples:


~~~text
feat: add repair approval flow

fix: correct SLA timer calculation

docs: update API documentation
~~~


# 17. Code Review Checklist


Before approval:


- Code follows standards
- Tests pass
- Security rules are considered
- Documentation is updated if needed


# 18. Related Documents


Development Guidelines:

~~~text
docs/06-Development/Development-Guidelines.md
~~~


Backend Architecture:

~~~text
docs/03-Architecture/Backend-Architecture.md
~~~


Security Architecture:

~~~text
docs/03-Architecture/Security-Architecture.md
~~~