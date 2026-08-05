# Dolphin Flow - Business Rules

Version:
0.1

Status:
Analysis & Documentation

Last Updated:
2026-08-05


# 1. Purpose

This document defines the business rules governing Dolphin Flow operations.

Business rules represent organizational decisions, policies, and constraints that must be respected by the system.


# 2. General Business Rules


## BR-001 Process Traceability

Every business process must have a complete history.

The system must record:

- Creation time
- Responsible user
- Department
- Status changes
- Approvals
- Documents
- Important actions


No process should exist without a traceable history.


---

## BR-002 Controlled Status Transition

Workflow statuses cannot be changed arbitrarily.

Every status transition must follow:

- Defined workflow rules
- User permissions
- Approval requirements


Example:

A repair request cannot move from:

"Received"

directly to:

"Completed"

without passing required stages.


---

## BR-003 Approval Integrity

An approved step represents a digital signature.

Approved records:

- Cannot be edited directly
- Must maintain approval history
- Require authorized override for changes


---

## BR-004 Override Permission

Only authorized users may bypass or modify workflow rules.

Every override must record:

- User
- Date/time
- Reason
- Previous state
- New state


---

# 3. Repair Process Business Rules


# BR-101 Repair Request Creation


A repair request is created when a device enters the organization.


Required information:


## Customer Information

- Customer name
- Contact information
- Address


## Device Information

- Device type
- IMEI
- Serial information (if available)


## Problem Information

- Customer reported issue
- Additional notes


A repair request cannot proceed without required information.


---

# BR-102 Multiple Devices in One Request


A single customer shipment may contain multiple devices.


Rules:

- One repair request may contain multiple devices.
- Each device must have independent status tracking.
- Each device must maintain its own repair history.


Example:
Repair Request #1001

Customer:
ABC Company

Devices:

Device 1:
IMEI: XXXXX

Device 2:
IMEI: YYYYY


---

# BR-103 Device Identity


IMEI is the primary device identifier.


Rules:

- A device may appear in multiple repair requests over time.
- Previous repair history must remain accessible.
- New repair requests must not overwrite previous history.


Device lifecycle:
Device
|
├── Repair Request 1
|
├── Repair Request 2
|
└── Repair Request N


---

# BR-104 Warranty Evaluation


Every repair request must pass warranty evaluation.


Responsible department:

Support


Possible results:


## Warranty Approved

Device follows warranty repair path.


## Warranty Rejected

Device follows paid repair path.


The decision must be recorded with:

- Reviewer
- Date
- Reason


---

# BR-105 Warranty Repair Flow


If warranty is approved:


Process:
Support Approval

↓

Repair Department

↓

Warehouse



No customer payment approval is required.


---

# BR-106 Paid Repair Flow


If warranty is rejected:


Process:

Support

↓

Cost Estimation

↓

Customer Approval

↓

Repair

↓

Final Cost

↓

Finance Verification

↓

Warehouse



---

# BR-107 Customer Cost Approval


Customer approval is required before paid repair starts.


Possible states:


## Approved

Continue repair process.


## Rejected

Process is closed or returned according to organizational policy.


## Waiting

Process remains pending.


---

# BR-108 Repair Completion


A repair is considered completed only when:


- Technical report is registered.
- Repair result is recorded.
- Required documents are attached.
- Device is transferred to next stage.


---

# BR-109 Financial Verification


For paid repairs:


Device cannot be delivered until:

- Payment is verified.
- Finance approval is completed.


---

# BR-110 Warehouse Receipt


Warehouse must confirm:


- Device received
- Physical condition
- Related documents


A warehouse receipt must be generated.


---

# BR-111 Shipping Completion


Administrative department must:


- Confirm customer address
- Register shipping information
- Record tracking number


A repair request is completed only after shipment information is recorded.


---

# 4. SLA Business Rules


# BR-201 SLA Assignment


Every workflow stage must have an SLA definition.


SLA includes:

- Allowed duration
- Warning threshold
- Escalation rule


---

# BR-202 SLA Ownership


Each SLA belongs to:

- A department
- A responsible role


---

# BR-203 SLA Escalation


When SLA is exceeded:


The system must:

- Generate notification
- Record violation
- Notify responsible manager


---

# 5. Document Rules


# BR-301 Document Attachment


Important process stages may require documents.


Examples:

- Repair forms
- Warehouse receipts
- Financial documents


---

# BR-302 Document Integrity


Uploaded documents:

- Must remain linked to their process
- Must have uploader information
- Must have upload date


---

# 6. Notification Rules


# BR-401 Event Notification


Important events must generate notifications.


Examples:

- New task assigned
- Approval required
- SLA warning
- Process completed


---

# 7. Process Completion Rules


# BR-501 Repair Case Completion


A repair request can be closed only when:


- All devices have final status.
- Required approvals exist.
- Required documents exist.
- Delivery information is recorded.


---

# 8. Future Business Rules


Future modules will add additional rules:

- Quality Management
- Customer Portal
- Purchase Workflow
- Internal Requests