# Dolphin Flow - UX Guidelines

Version:
0.1

Status:
UI/UX Planning

Last Updated:
2026-08-05


# 1. Purpose

This document defines user experience guidelines for Dolphin Flow.

The goal is to create an interface that helps users complete organizational processes accurately, quickly, and with minimum confusion.


# 2. UX Principles


## UX-001 User Orientation

At any moment, the user should understand:

- Where they are
- Which process they are viewing
- What action is expected


## UX-002 Reduce User Errors

The interface should prevent incorrect actions whenever possible.


Examples:

- Field validation
- Confirmation dialogs
- Permission-based actions


## UX-003 Show Process Context

Users should always see the current position of a process.


Example:

~~~text
Repair Request #10025


Received

✓

Warranty Check

✓

Repair

●

Finance

○

Shipping
~~~


## UX-004 Avoid Information Overload

Only relevant information should be displayed based on:

- User role
- Current task
- Process stage


# 3. User Journey Design


The system should follow the natural workflow of users.


Example:

Administrative User:


~~~text
Receive Device

        ↓

Register Customer

        ↓

Create Repair Request

        ↓

Send To Support
~~~


The interface should guide the user through these steps.


# 4. Dashboard UX


Each user should see a dashboard based on responsibilities.


Dashboard should contain:


## My Tasks

Tasks requiring user action.


## Pending Approvals

Items waiting for confirmation.


## Notifications

Important events.


## Performance Information

Relevant statistics.


# 5. Form Design Guidelines


Forms are a major part of Dolphin Flow.


## 5.1 Form Structure


Large forms should be divided into sections.


Example:


~~~text
Repair Request


1. Customer Information


2. Device Information


3. Problem Description


4. Attachments


5. Confirmation
~~~


## 5.2 Field Design


Each field should have:


- Clear label
- Example value when needed
- Validation message


## 5.3 Required Fields


Required fields must be clearly visible.


Example:


~~~text
IMEI *

* Required field
~~~


# 6. Workflow Interaction


Workflow actions should be explicit.


Bad example:


~~~text
Change Status
~~~


Better:


~~~text
Send To Repair Department
~~~


Users should understand the result of their action.


# 7. Approval UX


Approvals represent digital signatures.


Approval screens should show:


- Request information
- Related documents
- Previous history
- Decision options


Example:


~~~text
Warranty Approval


Device:
IMEI XXXXX


Decision:

[ Approve ]

[ Reject ]

Comment:
____________
~~~


# 8. Error Handling


Errors should be:


- Clear
- Understandable
- Actionable


Bad:


~~~text
Error 500
~~~


Better:


~~~text
Unable to save the request.

Please complete the missing field:
Customer Address
~~~


# 9. Confirmation Design


Important actions require confirmation.


Examples:


- Approving a request
- Rejecting a process
- Closing a workflow


Confirmation should explain:


- What will happen
- Whether the action is reversible


# 10. Data Display Guidelines


Information should be displayed according to importance.


Priority order:


1. Current status

2. Required action

3. Important details

4. History


# 11. History View Design


Every process should provide a timeline view.


Example:


~~~text
05 Aug 10:30

Request created

By:
Administrative User


05 Aug 14:20

Warranty approved

By:
Support User


06 Aug 09:00

Repair started

By:
Technician
~~~


# 12. Document Management UX


Documents should be easy to find.


Users should see:


- Document name
- Upload date
- Uploaded by
- Related stage


# 13. Notification UX


Notifications should be:


- Relevant
- Timely
- Actionable


Example:


~~~text
Repair Request #10025

Waiting for your approval.

[Open Request]
~~~


# 14. Search and Filtering


The system should provide powerful search.


Search examples:


- IMEI
- Request number
- Customer name
- Date range
- Status


# 15. Mobile Considerations


Although primary usage is desktop, important actions should work on mobile browsers.


Examples:


- Approvals
- Notifications
- Status checking


# 16. Accessibility Guidelines


The interface should consider:


- Readable text
- Clear colors
- Keyboard support
- Simple navigation


# 17. Future UX Improvements


Possible improvements:


- Drag and drop workflow designer
- AI assistant interface
- Smart recommendations
- Customer self-service portal


# 18. Related Documents


Design System:

~~~text
docs/05-UI-UX/Design-System.md
~~~


Frontend Architecture:

~~~text
docs/03-Architecture/Frontend-Architecture.md
~~~