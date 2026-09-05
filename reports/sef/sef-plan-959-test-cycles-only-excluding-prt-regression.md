# [SEF Phase 1 | HCM and Payroll](https://twoa.atlassian.net/jira/plans/959/scenarios/959/timeline?vid=1053)

- Source: `tmp_plan_issues_live_15891.json` (Plan 959 timeline snapshot)
- Scope: `type == Test Cycle` plus direct children of those cycles
- Exclusions: summaries containing `Production Rehearsal Testing` or `Regression Testing`
- Included test cycles: 11
- Included child items: 5

```mermaid
gantt
    title SEF Phase 1 | HCM and Payroll
    dateFormat YYYY-MM-DD
    axisFormat %d %b %Y

    section Parent Test Cycles (Target Scope)
    PDE-4599 | Payroll | Non Integrated Parallel Run One | Testing :pde_4599, 2026-09-28, 2026-10-23
    PDE-4601 | HCM/Payroll | Foundation | Connectivity Testing :pde_4601, 2026-09-28, 2026-10-23
    PDE-4602 | HCM/Payroll | Foundation | System Integration Testing :pde_4602, 2026-09-28, 2026-10-23
    PDE-4677 | Integration | System Integration Testing :pde_4677, 2026-10-05, 2026-12-13
    CHILD | PDE-4706 | of PDE-4677 | Alma (Story) | System Integration Testing :pde_4706, 2026-10-05, 2026-10-18
    CHILD | PDE-4705 | of PDE-4677 | SmartConnect (Story) | System Integration Testing :pde_4705, 2026-10-19, 2026-11-01
    CHILD | PDE-4704 | of PDE-4677 | EcoPortal (Story) | System Integration Testing :pde_4704, 2026-11-02, 2026-11-15
    CHILD | PDE-4703 | of PDE-4677 | CheckMate (Story) | System Integration Testing :pde_4703, 2026-11-16, 2026-11-29
    CHILD | PDE-4702 | of PDE-4677 | MicroSoft Fabric (Story) | System Integration Testing :pde_4702, 2026-11-30, 2026-12-13
    PDE-4727 | HCM/Payroll | End to End | Connectivity Testing :pde_4727, 2026-11-02, 2026-11-06
    PDE-4604 | Testing | End to End Testing :pde_4604, 2026-11-09, 2026-12-18
    PDE-4608 | Testing | User Acceptance Testing :pde_4608, 2027-01-15, 2027-02-19
    PDE-4730 | HCM/Payroll | Parallel | Connectivity Testing :pde_4730, 2027-01-18, 2027-01-22
    PDE-4616 | Testing | Parallel Run Two | Testing :pde_4616, 2027-01-25, 2027-02-12
    PDE-4729 | Testing | Parallel Run Three | Testing :pde_4729, 2027-02-15, 2027-03-05
    PDE-4731 | Payroll | PRD | Connectivity Testing :pde_4731, 2027-03-22, 2027-03-26
```
