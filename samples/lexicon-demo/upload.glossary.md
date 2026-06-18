# Glossary — File upload (approved terms)

- **Upload_Service**: service that accepts and stores uploaded files
- **upload_request**: a user request to upload a file
- **file_blob**: the binary contents of an uploaded file
- **file_size**: the size of an uploaded file
- **virus_scan**: the malware scan run over an uploaded file
- **scan_status**: lifecycle state of a virus_scan
- **storage_key**: the key under which a clean file is stored
- **upload_status**: lifecycle state of an upload_request
- **FILE_TOO_LARGE**: error code when file_size exceeds the limit
- **SCAN_FAILED**: error code when a virus_scan detects malware or errors
