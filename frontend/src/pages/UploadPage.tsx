import { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { Upload, File, CheckCircle, XCircle, Loader } from 'lucide-react';
import { documentApi } from '../services/api';
import type { UploadProgress } from '../types';

export default function UploadPage() {
  const [uploads, setUploads] = useState<UploadProgress[]>([]);

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    for (const file of acceptedFiles) {
      const uploadId = crypto.randomUUID();

      // Add to upload list
      setUploads((prev) => [
        ...prev,
        {
          upload_id: uploadId,
          filename: file.name,
          progress: 0,
          status: 'pending',
        },
      ]);

      try {
        // Get presigned URL
        setUploads((prev) =>
          prev.map((u) =>
            u.upload_id === uploadId ? { ...u, status: 'uploading' } : u
          )
        );

        const { presigned_url, upload_id: serverUploadId } =
          await documentApi.getPresignedUrl(file.name, 'application/pdf', file.size);

        // Upload to S3
        await fetch(presigned_url, {
          method: 'PUT',
          body: file,
          headers: {
            'Content-Type': 'application/pdf',
          },
        });

        // Update progress
        setUploads((prev) =>
          prev.map((u) =>
            u.upload_id === uploadId
              ? { ...u, progress: 50, status: 'processing' }
              : u
          )
        );

        // Complete upload
        await documentApi.completeUpload(serverUploadId);

        // Mark complete
        setUploads((prev) =>
          prev.map((u) =>
            u.upload_id === uploadId
              ? { ...u, progress: 100, status: 'complete' }
              : u
          )
        );
      } catch (error) {
        setUploads((prev) =>
          prev.map((u) =>
            u.upload_id === uploadId
              ? {
                  ...u,
                  status: 'error',
                  error: error instanceof Error ? error.message : 'Upload failed',
                }
              : u
          )
        );
      }
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
    },
    multiple: true,
  });

  return (
    <div className="flex-1 p-8 overflow-auto">
      <div className="max-w-3xl mx-auto">
        <h1 className="text-2xl font-bold mb-6">Upload Documents</h1>

        {/* Dropzone */}
        <div
          {...getRootProps()}
          className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-colors ${
            isDragActive
              ? 'border-primary-500 bg-primary-50'
              : 'border-gray-300 hover:border-primary-400 hover:bg-gray-50'
          }`}
        >
          <input {...getInputProps()} />
          <Upload
            className={`w-12 h-12 mx-auto mb-4 ${
              isDragActive ? 'text-primary-500' : 'text-gray-400'
            }`}
          />
          {isDragActive ? (
            <p className="text-primary-600 font-medium">Drop PDFs here...</p>
          ) : (
            <div>
              <p className="text-gray-600 font-medium">
                Drag & drop PDF files here
              </p>
              <p className="text-gray-400 text-sm mt-1">
                or click to select files
              </p>
            </div>
          )}
        </div>

        {/* Upload List */}
        {uploads.length > 0 && (
          <div className="mt-8">
            <h2 className="text-lg font-semibold mb-4">Uploads</h2>
            <div className="space-y-3">
              {uploads.map((upload) => (
                <div
                  key={upload.upload_id}
                  className="flex items-center gap-4 p-4 bg-white rounded-lg border"
                >
                  <File className="w-8 h-8 text-gray-400" />
                  <div className="flex-1 min-w-0">
                    <p className="font-medium truncate">{upload.filename}</p>
                    <div className="mt-1">
                      {upload.status === 'uploading' && (
                        <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-primary-500 transition-all"
                            style={{ width: `${upload.progress}%` }}
                          />
                        </div>
                      )}
                      {upload.status === 'processing' && (
                        <p className="text-sm text-gray-500">Processing...</p>
                      )}
                      {upload.status === 'error' && (
                        <p className="text-sm text-red-500">{upload.error}</p>
                      )}
                    </div>
                  </div>
                  <div>
                    {upload.status === 'uploading' && (
                      <Loader className="w-5 h-5 text-primary-500 animate-spin" />
                    )}
                    {upload.status === 'processing' && (
                      <Loader className="w-5 h-5 text-primary-500 animate-spin" />
                    )}
                    {upload.status === 'complete' && (
                      <CheckCircle className="w-5 h-5 text-green-500" />
                    )}
                    {upload.status === 'error' && (
                      <XCircle className="w-5 h-5 text-red-500" />
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
