ARTIFACT: SPEC
TITLE: File Upload with Malware Scanning

REQ: UPL-001
GIVEN: a caller has constructed an upload_request containing a file_blob
WHEN: the caller submits the upload_request to Upload_Service
THEN: Upload_Service MUST validate the file_size of the file_blob against the configured maximum limit before any further processing
OUTPUT: a rejection with upload_status set to FILE_TOO_LARGE if the file_size exceeds the limit, or continued processing if within the limit

REQ: UPL-002
GIVEN: an upload_request has passed file_size validation
WHEN: Upload_Service initiates processing of the file_blob
THEN: Upload_Service MUST execute a virus_scan against the file_blob and produce a scan_status result
OUTPUT: scan_status is set to either clean or infected after the virus_scan completes

REQ: UPL-003
GIVEN: the virus_scan of a file_blob has completed with a clean scan_status
WHEN: Upload_Service proceeds to store the file_blob
THEN: Upload_Service MUST persist the file_blob to durable storage and generate a unique storage_key
OUTPUT: a storage_key that uniquely identifies the persisted file_blob

REQ: UPL-004
GIVEN: the file_blob has been persisted and a storage_key has been generated
WHEN: Upload_Service completes the upload transaction
THEN: Upload_Service MUST return a response containing the storage_key with upload_status set to STORED
OUTPUT: a response containing the storage_key and upload_status of STORED delivered to the caller

REQ: UPL-005
GIVEN: the virus_scan of a file_blob has completed with an infected scan_status
WHEN: Upload_Service evaluates the scan_status
THEN: Upload_Service MUST reject the upload_request and discard the file_blob without persisting it
OUTPUT: a response with upload_status set to SCAN_FAILED and no storage_key

REQ: UPL-006
GIVEN: an upload_request has been submitted
WHEN: Upload_Service begins processing
THEN: Upload_Service MUST complete file_size validation before initiating the virus_scan
OUTPUT: a deterministic processing order where no virus_scan resources are consumed for oversized files

AC: UPL-AC-001
GIVEN: a caller submits an upload_request with a file_blob whose file_size is within the allowed maximum
WHEN: the virus_scan returns a clean scan_status
THEN: the caller receives a response containing a valid storage_key and upload_status of STORED

AC: UPL-AC-002
GIVEN: a caller submits an upload_request with a file_blob whose file_size exceeds the allowed maximum
WHEN: Upload_Service evaluates the file_size
THEN: the caller receives a rejection response with upload_status of FILE_TOO_LARGE and no virus_scan is performed

AC: UPL-AC-003
GIVEN: a caller submits an upload_request with a file_blob that contains malicious content
WHEN: the virus_scan returns an infected scan_status
THEN: the caller receives a rejection response with upload_status of SCAN_FAILED and the file_blob is not persisted

ERROR: UPL-ERR-001
WHEN: the file_size of the submitted file_blob exceeds the configured maximum
THEN: reject the upload_request and return upload_status of FILE_TOO_LARGE without initiating a virus_scan
ERROR_CODE: FILE_TOO_LARGE

ERROR: UPL-ERR-002
WHEN: the virus_scan returns an infected scan_status for the submitted file_blob
THEN: reject the upload_request, discard the file_blob, and return upload_status of SCAN_FAILED
ERROR_CODE: SCAN_FAILED
