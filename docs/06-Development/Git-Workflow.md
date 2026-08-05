# Dolphin Flow - Git Workflow

Version:
0.1

Status:
Development Standard

Last Updated:
2026-08-05


# 1. Purpose

This document defines the Git workflow and repository management standards for Dolphin Flow.

The purpose is to ensure:

- Controlled development
- Clear history of changes
- Safe collaboration
- Easy project continuation from any location


# 2. Repository Philosophy

The repository is the single source of truth for:


- Source code
- Documentation
- Architecture decisions
- Configuration examples
- Project history


Any important project decision must be reflected in the repository.


# 3. Repository Structure


High-level structure:


~~~text
Dolphin-Flow/

├── backend/

├── frontend/

├── docs/

├── deployment/

├── scripts/

└── README.md
~~~


# 4. Branch Strategy


The project uses the following branches:


# 4.1 Main Branch


Name:


~~~text
main
~~~


Purpose:


Production-ready versions.


Rules:


- Stable code only
- No direct development
- Requires review before merge


---

# 4.2 Development Branch


Name:


~~~text
develop
~~~


Purpose:


Main integration branch.


Contains:


- Completed features
- Tested changes


---

# 4.3 Feature Branches


Format:


~~~text
feature/<feature-name>
~~~


Examples:


~~~text
feature/repair-workflow

feature/sla-engine

feature/customer-notification
~~~


Purpose:


Development of new capabilities.


---

# 4.4 Bugfix Branches


Format:


~~~text
bugfix/<issue-name>
~~~


Examples:


~~~text
bugfix/login-error

bugfix/report-filter
~~~


# 5. Branch Flow


Standard flow:


~~~text
feature branch

        |

        v

develop

        |

        v

main
~~~


# 6. Commit Standards


Commits should be:

- Small
- Clear
- Focused


A commit should represent one logical change.


# 7. Commit Message Format


Format:


~~~text
type: description
~~~


Allowed types:


| Type | Usage |
|---|---|
| feat | New feature |
| fix | Bug correction |
| docs | Documentation |
| refactor | Code improvement |
| test | Tests |
| chore | Maintenance |


Examples:


~~~text
feat: add repair request model

docs: update workflow documentation

fix: correct SLA calculation
~~~


# 8. Documentation Commits


Documentation changes should be committed separately when possible.


Example:


~~~text
docs: add security architecture document
~~~


# 9. Version Management


The project uses semantic versioning.


Format:


~~~text
MAJOR.MINOR.PATCH
~~~


Example:


~~~text
1.0.0
~~~


Meaning:


Major:

Breaking changes


Minor:

New features


Patch:

Bug fixes


# 10. Release Process


A release follows:


~~~text
Develop branch

        |

Testing

        |

Release preparation

        |

Main branch

        |

Version tag
~~~


# 11. Git Tags


Each release should have a tag.


Example:


~~~text
v1.0.0

v1.1.0
~~~


# 12. Pull Request Rules


Before merging:


Required:


- Description of change
- Related issue/task
- Testing result
- Documentation update if needed


# 13. Commit Frequency


Recommended:


- Commit after completing a meaningful step
- Avoid very large commits
- Avoid committing unfinished work


# 14. Sensitive Data Rules


The repository must never contain:


- Passwords
- API keys
- Database credentials
- Private certificates


Sensitive values must use environment variables.


# 15. Documentation Synchronization


Changes affecting architecture must update:


~~~text
docs/

Architecture documents

Decision Log

Change Log
~~~


# 16. Backup and Availability


The repository should be hosted in a reliable remote Git service.


The team should maintain:

- Regular synchronization
- Access credentials
- Backup strategy


# 17. Future Improvements


Possible additions:


- Automated CI/CD
- Automated testing pipeline
- Code quality checks
- Deployment automation


# 18. Related Documents


Development Guidelines:

~~~text
docs/06-Development/Development-Guidelines.md
~~~


Decision Log:

~~~text
docs/01-Project/Decision-Log.md
~~~


Change Log:

~~~text
CHANGELOG.md
~~~