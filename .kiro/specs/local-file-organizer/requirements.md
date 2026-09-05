# Requirements Document

## Introduction

The Local File Organizer is an AI-powered desktop application that analyzes files in a user-specified directory, categorizes them by inspecting both file contents and metadata, generates an appropriate folder structure, and moves files into their designated folders. The system leverages AI models to produce accurate, context-aware categorization that goes beyond simple extension-based sorting, and generates per-file metadata records to improve future categorization decisions.

## Glossary

- **Organizer**: The Local File Organizer application as a whole.
- **Source_Directory**: The user-selected directory whose files are to be organized.
- **Target_Directory**: The root directory under which the Organizer creates category folders. May be the same as or different from the Source_Directory.
- **File_Inspector**: The component responsible for reading file contents and extracting raw text or binary signals for analysis.
- **AI_Categorizer**: The component that uses an AI model to assign a category and subcategory to each file based on content signals, metadata, filename, and extension.
- **Folder_Generator**: The component that creates category folders inside the Target_Directory.
- **File_Mover**: The component that moves files from the Source_Directory into the appropriate category folders.
- **Metadata_Store**: The persistent storage (e.g., a JSON or SQLite file) that holds per-file metadata records generated during and after organization.
- **Category**: A top-level label assigned to a file by the AI_Categorizer (e.g., "Documents", "Images", "Code", "Finance").
- **Subcategory**: An optional second-level label that refines the Category (e.g., "Invoices" under "Finance").
- **Metadata_Record**: A structured object containing file path, hash, size, MIME type, extracted text snippet, assigned Category, Subcategory, confidence score, and timestamp.
- **Confidence_Score**: A numeric value in the range [0.0, 1.0] representing the AI_Categorizer's certainty about a category assignment.
- **Dry_Run**: An execution mode in which the Organizer simulates all actions without writing any changes to disk.
- **Conflict**: A situation where a file with the same name already exists in the destination folder.

---

## Requirements

### Requirement 1: Source Directory Selection

**User Story:** As a user, I want to select a source directory to organize, so that I can control which files the Organizer processes.

#### Acceptance Criteria

1. THE Organizer SHALL accept a Source_Directory path as a required input parameter at startup.
2. IF the provided Source_Directory path does not exist, is not accessible, or points to a file rather than a directory, THEN THE Organizer SHALL report a descriptive error and exit without modifying any files.
3. THE Organizer SHALL accept an optional Target_Directory path; WHERE a Target_Directory is not specified, THE Organizer SHALL use the Source_Directory as the Target_Directory.
4. IF the provided Target_Directory path does not exist, THEN THE Organizer SHALL create it and all necessary intermediate directories before proceeding.
5. IF the Target_Directory cannot be created due to a permissions error or invalid path, THEN THE Organizer SHALL report a descriptive error and exit without modifying any files.

---

### Requirement 2: File Discovery

**User Story:** As a user, I want the Organizer to discover all files in the source directory, so that no files are missed during organization.

#### Acceptance Criteria

1. THE Organizer SHALL recursively enumerate all files within the Source_Directory, traversing all subdirectories to unlimited depth.
2. THE Organizer SHALL allow the user to specify one or more glob patterns to exclude from enumeration; WHEN an exclusion pattern is provided, THE Organizer SHALL skip all files and directories whose paths match that pattern.
3. IF a symbolic link's resolved target path does not begin with the canonical absolute path of the Source_Directory, THEN THE Organizer SHALL skip that symbolic link and include it in a skipped-items count reported at the end of discovery.
4. WHEN file discovery is complete, THE Organizer SHALL report the total count of discovered files, the count of skipped symbolic links, and the count of excluded files before proceeding to organization.
5. IF the Source_Directory is not readable during enumeration, THEN THE Organizer SHALL halt discovery and emit an error indicating the directory path and the reason access failed.

---

### Requirement 3: File Content Inspection

**User Story:** As a user, I want the Organizer to inspect file contents when possible, so that categorization is based on actual content rather than just filename or extension.

#### Acceptance Criteria

1. WHEN a file's MIME type indicates a text-based format (including plain text, Markdown, source code, CSV, HTML, and XML), THE File_Inspector SHALL extract up to the first 4,096 characters of content for analysis.
2. WHEN a file is a PDF document, THE File_Inspector SHALL extract readable text from up to the first 10 pages for analysis.
3. WHEN a file is a Microsoft Office document (.docx, .xlsx, .pptx), THE File_Inspector SHALL extract readable text from the document body, up to a maximum of 4,096 characters, for analysis.
4. IF a file's content cannot be extracted due to a binary, encrypted, or unsupported format, THEN THE File_Inspector SHALL record a content extraction status of "unavailable" in the file's Metadata_Record and proceed using filename and extension signals only.
5. THE File_Inspector SHALL compute a SHA-256 hash of each file's full binary content and store it in the file's Metadata_Record.
6. IF content extraction fails due to a read error or processing exception, THEN THE File_Inspector SHALL record a content extraction status of "failed" in the file's Metadata_Record and proceed using filename and extension signals only.
7. WHEN a text-based file's content is extracted, THE File_Inspector SHALL record the character count of the extracted content (between 0 and 4,096 inclusive) in the file's Metadata_Record.

---

### Requirement 4: AI-Based Categorization

**User Story:** As a user, I want files to be categorized by an AI model, so that the assigned categories reflect the actual purpose and content of each file.

#### Acceptance Criteria

1. WHEN all content signals for a file are assembled, THE AI_Categorizer SHALL assign exactly one Category and one optional Subcategory to the file.
2. THE AI_Categorizer SHALL produce a Confidence_Score between 0.0 and 1.0 for each category assignment.
3. WHERE a minimum confidence threshold is configured by the user with a value between 0.0 and 1.0, THE AI_Categorizer SHALL set the Metadata_Record review_required field to true and omit the file from automatic moving for any file whose Confidence_Score falls below that threshold.
4. THE AI_Categorizer SHALL use the extracted text content, filename, file extension, file size, and MIME type as inputs to the categorization model.
5. THE AI_Categorizer SHALL use the Category, Subcategory, and Confidence_Score values from the existing Metadata_Record for files with the same SHA-256 hash, skipping re-categorization for duplicate files.
6. IF the AI model service is unavailable or returns a non-success response, THEN THE AI_Categorizer SHALL assign a Category based solely on the file extension, set the Metadata_Record fallback_used field to true, and produce a Confidence_Score of 0.0 for the assignment.
7. IF the AI model returns a Category value that does not exist in the configured category taxonomy, THEN THE AI_Categorizer SHALL discard the model response, set the Metadata_Record review_required field to true, and omit the file from automatic moving.
8. IF the AI model service is unavailable and the file extension is absent or unrecognized, THEN THE AI_Categorizer SHALL assign the Category value "Uncategorized", set the Metadata_Record fallback_used field to true, and set the Metadata_Record review_required field to true.

---

### Requirement 5: Metadata Generation

**User Story:** As a developer or power user, I want the Organizer to generate metadata for each processed file, so that categorization decisions are auditable and future runs are faster.

#### Acceptance Criteria

1. THE Organizer SHALL create or update a Metadata_Record for every file it processes, regardless of whether the file is moved.
2. EACH Metadata_Record SHALL contain: original file path, destination file path, SHA-256 hash, file size in bytes, MIME type, extracted text snippet (up to 512 characters), assigned Category, assigned Subcategory (if any), a Confidence_Score between 0.00 and 1.00 inclusive, categorization method ("ai" or "fallback"), and an ISO 8601 timestamp reflecting the time the record was created or updated.
3. WHEN a run completes, THE Metadata_Store SHALL persist all Metadata_Records to a single file named `organizer-metadata.json` inside the Target_Directory.
4. IF the `organizer-metadata.json` file cannot be written to the Target_Directory, THEN THE Organizer SHALL report an error indicating the write failure and preserve the in-memory Metadata_Records for the duration of the run without aborting file processing.
5. WHEN a file already has a Metadata_Record with a matching SHA-256 hash and Category, THE Organizer SHALL skip re-processing that file and reuse the existing record.
6. WHEN a subsequent run starts and an existing `organizer-metadata.json` is present in the Target_Directory, THE Organizer SHALL merge new and updated Metadata_Records into the existing store, keyed by original file path, without removing records for files not encountered in the current run.
7. IF a file's SHA-256 hash matches an existing Metadata_Record but the Category differs, THEN THE Organizer SHALL re-process the file and overwrite the existing record with the new categorization result.

---

### Requirement 6: Folder Structure Generation

**User Story:** As a user, I want the Organizer to automatically create folders for each category, so that I do not have to create them manually.

#### Acceptance Criteria

1. WHEN a new Category is identified, THE Folder_Generator SHALL create a corresponding folder inside the Target_Directory using the Category label as the folder name.
2. WHEN a Subcategory is assigned, THE Folder_Generator SHALL create a subfolder inside the Category folder using the Subcategory label as the subfolder name.
3. THE Folder_Generator SHALL sanitize Category and Subcategory labels to produce valid folder names on the target operating system, replacing any disallowed characters with underscores.
4. IF a folder with the derived name already exists, THEN THE Folder_Generator SHALL reuse the existing folder without returning an error.
5. IF the Folder_Generator cannot create a required folder due to a permissions error, THEN THE Organizer SHALL log the error and place the affected files in a folder named `_unplaced` inside the Target_Directory.

---

### Requirement 7: File Moving

**User Story:** As a user, I want the Organizer to move files into their assigned category folders, so that my directory is organized without duplicating storage.

#### Acceptance Criteria

1. WHEN a Category and destination folder are determined for a file, THE File_Mover SHALL move the file from its current path to the destination folder.
2. WHEN a Conflict is detected, THE File_Mover SHALL rename the incoming file by appending an underscore and an incrementing integer suffix before the file extension (e.g., `report_1.pdf`) until a unique name is found, up to a maximum suffix of 9,999.
3. THE File_Mover SHALL preserve the original file's last-modified timestamp after the move.
4. IF a file move operation fails due to a permissions error or I/O error, THEN THE File_Mover SHALL log the error with the file path and reason, skip that file, and continue processing remaining files.
5. WHEN a file is flagged for manual review (review_required is true), THE File_Mover SHALL place it in a folder named `_review` inside the Target_Directory instead of the assigned Category folder.
6. IF the conflict suffix reaches 9,999 and a unique filename still cannot be found, THEN THE File_Mover SHALL log an error for that file, skip it, and continue processing remaining files.

---

### Requirement 8: Dry Run Mode

**User Story:** As a user, I want to preview what the Organizer will do before committing changes, so that I can verify the proposed organization before files are moved.

#### Acceptance Criteria

1. WHERE Dry_Run mode is enabled, THE Organizer SHALL perform all discovery, inspection, and categorization steps without creating folders or moving files.
2. WHERE Dry_Run mode is enabled, THE Organizer SHALL output a structured report listing each file, its proposed destination path, its assigned Category and Subcategory, and its Confidence_Score.
3. WHERE Dry_Run mode is enabled, THE Organizer SHALL NOT write or modify the Metadata_Store.
4. WHERE Dry_Run mode is enabled, THE Organizer SHALL indicate in the report which files would be placed in `_review` and which would be placed in `_unplaced`.

---

### Requirement 9: Progress Reporting and Logging

**User Story:** As a user, I want real-time feedback on the organization process, so that I can monitor progress and diagnose issues.

#### Acceptance Criteria

1. WHILE the Organizer is processing files, THE Organizer SHALL display a progress indicator showing the number of files processed and the total number of files discovered.
2. THE Organizer SHALL write structured log entries to a log file named `organizer.log` inside the Target_Directory for every file processed, including the action taken, destination path, and any errors encountered.
3. WHEN the Organizer completes a run, THE Organizer SHALL display a summary report showing: total files processed, total files moved, total files skipped, total files flagged for review, total files placed in `_unplaced`, and total errors encountered.
4. IF the Organizer is interrupted by the user (e.g., via SIGINT or Ctrl+C) before completion, THEN THE Organizer SHALL flush all completed Metadata_Records to the Metadata_Store before exiting and display a partial summary of actions taken up to the point of interruption.
5. WHEN a log entry is written, THE Organizer SHALL include an ISO 8601 timestamp, the log level (INFO, WARN, or ERROR), the file path, and the action or error description in each log entry.

---

### Requirement 10: Configuration

**User Story:** As a user, I want to configure the Organizer's behavior through a configuration file or command-line flags, so that I can tailor it to my workflow without modifying code.

#### Acceptance Criteria

1. THE Organizer SHALL support a YAML or JSON configuration file that sets default values for all configurable parameters, including Source_Directory, Target_Directory, exclusion patterns, minimum confidence threshold, AI model endpoint, and Dry_Run mode.
2. WHEN both a configuration file and command-line flags are provided, THE Organizer SHALL give command-line flags precedence over configuration file values.
3. IF the configuration file exists but contains invalid syntax, THEN THE Organizer SHALL report a descriptive parse error identifying the file path and the line or position of the error, and exit without processing any files.
4. THE Organizer SHALL provide a `--help` flag that prints all available configuration options with descriptions, accepted value types, and default values.
5. IF a required parameter (Source_Directory) is absent from both the configuration file and command-line flags, THEN THE Organizer SHALL report a descriptive error naming the missing parameter and exit without processing any files.
