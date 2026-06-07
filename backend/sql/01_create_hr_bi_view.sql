-- Create this once in the HR analytics database before using Phase 2.

CREATE OR REPLACE VIEW hr_mvp.vw_hr_employee_analytics AS
SELECT
    e.employee_id,

    e.gender,
    e.marital_status,
    e.birth_date,
    COALESCE(
        e.age,
        EXTRACT(YEAR FROM age(CURRENT_DATE, e.birth_date))::int
    ) AS age,

    ag.age_group_title,

    e.hire_date,
    e.hire_year,
    e.service_years,
    e.is_active,

    d.department_id,
    d.department_code,
    d.department_name,
    d.service_domain,
    d.parent_department_id,
    d.department_level,
    d.approved_headcount AS department_approved_headcount,
    d.criticality_level,

    l.location_id,
    l.province,
    l.city,
    l.site_name,
    l.location_type,

    p.position_id,
    p.position_code,
    p.position_title,
    p.position_level,
    p.job_family,
    p.is_expert_role,
    p.min_education_rank,

    el.education_title,
    el.education_rank,
    el.education_category,
    ee.field_of_study,
    ee.graduation_year,

    c.employment_type,
    c.contract_type,
    c.is_contractor,
    c.contract_start_date,
    c.contract_end_date

FROM hr_mvp.hr_employees e

LEFT JOIN hr_mvp.hr_departments d
    ON e.department_id = d.department_id

LEFT JOIN hr_mvp.hr_locations l
    ON e.location_id = l.location_id

LEFT JOIN hr_mvp.hr_positions p
    ON e.position_id = p.position_id

LEFT JOIN hr_mvp.hr_contracts c
    ON e.employee_id = c.employee_id
   AND c.is_current = true

LEFT JOIN hr_mvp.hr_employee_education ee
    ON e.employee_id = ee.employee_id
   AND ee.is_latest = true

LEFT JOIN hr_mvp.hr_education_levels el
    ON ee.education_level_id = el.education_level_id

LEFT JOIN hr_mvp.hr_age_groups ag
    ON COALESCE(
        e.age,
        EXTRACT(YEAR FROM age(CURRENT_DATE, e.birth_date))::int
    ) BETWEEN ag.min_age AND ag.max_age

WHERE e.is_active = TRUE;
