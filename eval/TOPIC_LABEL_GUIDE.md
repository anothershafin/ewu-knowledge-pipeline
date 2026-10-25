# Topic label guide

Open `annotation_sample.csv`. For each row, read the `text` column and enter one label in `human_topic`. Enter your own name in `reviewer`. Hide `rule_topic` while labeling so the automatic prediction does not influence your judgment. Leave the other columns unchanged.

| Enter this exact label | Main subject of the passage |
|---|---|
| `admission` | Applying, entry requirements, admission tests or admission documents |
| `registration` | Registering for courses, advising, adding/dropping, withdrawal or leave |
| `fees_refunds` | Tuition, charges, payments or refunds |
| `grading_cgpa` | Letter grades, grade points, GPA/CGPA calculation or incomplete grades |
| `probation_dismissal` | Academic probation, dismissal or recovery requirements |
| `retake` | Repeating a course or how a repeated attempt is counted |
| `attendance` | Class attendance, absence or attendance requirements |
| `graduation` | Completing a degree, required credits or graduation eligibility |
| `scholarship` | Scholarships, financial aid or tuition waivers |
| `conduct_discipline` | Student conduct, misconduct, disciplinary procedures or sanctions |
| `plagiarism_ai` | Plagiarism, academic honesty or permitted/prohibited AI use |
| `grievance` | Complaints, grievances or the grievance process |
| `course_info` | A course's title, credits, prerequisites, objectives, syllabus or outcomes |
| `calendar` | Semester schedules, examination dates or dated deadlines |
| `online_classes` | Online teaching platforms, access or participation guidance |
| `other` | A passage whose main subject does not fit the categories above |

Choose the main purpose of the passage, rather than a word that happens to appear. For example, a course description mentioning assessment is normally `course_info`; a university-wide grading rule is `grading_cgpa`. A general add/drop procedure is `registration`; a list of specific semester dates is `calendar`.

If a passage is ambiguous, use its `section_path` and source page for context. Choose the best single label, and keep a separate note of the row's `chunk_id` if you want to discuss it. An uncertain label should not be replaced by copying the automatic prediction.

Start with ten rows, save as CSV UTF-8, and have the file structure checked before completing all 100. These labels are the independent human comparison; there is no target agreement score to aim for.
