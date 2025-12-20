import { useState, useEffect } from 'react';
import { Settings, Cloud, HardDrive, Loader, Save, AlertCircle, CheckCircle } from 'lucide-react';
import toast from 'react-hot-toast';
import { preferencesApi } from '../services/api';
import type { StoragePreferences } from '../types';

const ALLOWED_PATH_PREFIXES = ['/data/', '/storage/', '/home/', '/Users/', '/tmp/'];

function validateLocalPath(path: string): string | null {
  if (!path) {
    return 'Local path is required when using local storage';
  }
  if (!path.startsWith('/')) {
    return 'Path must be absolute (start with /)';
  }
  if (path.includes('..')) {
    return 'Path cannot contain ".." (path traversal)';
  }
  const matchesPrefix = ALLOWED_PATH_PREFIXES.some((prefix) =>
    path.startsWith(prefix) || path === prefix.slice(0, -1)
  );
  if (!matchesPrefix) {
    return `Path must start with one of: ${ALLOWED_PATH_PREFIXES.join(', ')}`;
  }
  return null;
}

export default function SettingsPage() {
  const [storageType, setStorageType] = useState<'s3' | 'local'>('s3');
  const [localPath, setLocalPath] = useState('');
  const [bucket, setBucket] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState('');
  const [pathError, setPathError] = useState<string | null>(null);
  const [hasChanges, setHasChanges] = useState(false);
  const [originalPrefs, setOriginalPrefs] = useState<StoragePreferences | null>(null);

  useEffect(() => {
    loadPreferences();
  }, []);

  useEffect(() => {
    if (originalPrefs) {
      const changed =
        storageType !== originalPrefs.type ||
        localPath !== (originalPrefs.local_path || '') ||
        bucket !== (originalPrefs.bucket || '');
      setHasChanges(changed);
    }
  }, [storageType, localPath, bucket, originalPrefs]);

  useEffect(() => {
    if (storageType === 'local' && localPath) {
      setPathError(validateLocalPath(localPath));
    } else {
      setPathError(null);
    }
  }, [storageType, localPath]);

  const loadPreferences = async () => {
    try {
      setIsLoading(true);
      const prefs = await preferencesApi.get();
      const storage = prefs.storage || { type: 's3' };
      setStorageType(storage.type);
      setLocalPath(storage.local_path || '');
      setBucket(storage.bucket || '');
      setOriginalPrefs(storage);
    } catch (err) {
      setError('Failed to load preferences');
      console.error('Error loading preferences:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async () => {
    if (storageType === 'local') {
      const validationError = validateLocalPath(localPath);
      if (validationError) {
        setPathError(validationError);
        toast.error(validationError);
        return;
      }
    }

    try {
      setIsSaving(true);
      const storage: StoragePreferences = {
        type: storageType,
        ...(storageType === 'local' && localPath ? { local_path: localPath } : {}),
        ...(storageType === 's3' && bucket ? { bucket } : {}),
      };

      const updated = await preferencesApi.update({ storage });
      setOriginalPrefs(updated.storage);
      setHasChanges(false);
      toast.success('Storage preferences saved successfully');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to save preferences';
      toast.error(message);
      console.error('Error saving preferences:', err);
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b px-6 py-4">
        <div className="flex items-center gap-3">
          <Settings className="w-6 h-6 text-gray-600" />
          <h1 className="text-xl font-semibold text-gray-900">Settings</h1>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-2xl mx-auto p-6">
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 text-red-700 rounded-lg flex items-center gap-2">
            <AlertCircle className="w-5 h-5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Storage Preferences Card */}
        <div className="bg-white rounded-lg shadow-sm border">
          <div className="px-6 py-4 border-b">
            <h2 className="text-lg font-medium text-gray-900">Storage Preferences</h2>
            <p className="text-sm text-gray-500 mt-1">
              Choose where your uploaded documents are stored
            </p>
          </div>

          <div className="p-6 space-y-6">
            {/* Storage Type Selection */}
            <div className="space-y-3">
              <label className="block text-sm font-medium text-gray-700">
                Storage Backend
              </label>
              <div className="grid grid-cols-2 gap-4">
                {/* S3 Option */}
                <button
                  type="button"
                  onClick={() => setStorageType('s3')}
                  className={`relative flex flex-col items-center p-4 border-2 rounded-lg transition-all ${
                    storageType === 's3'
                      ? 'border-primary-500 bg-primary-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <Cloud
                    className={`w-8 h-8 mb-2 ${
                      storageType === 's3' ? 'text-primary-500' : 'text-gray-400'
                    }`}
                  />
                  <span
                    className={`font-medium ${
                      storageType === 's3' ? 'text-primary-700' : 'text-gray-700'
                    }`}
                  >
                    Amazon S3
                  </span>
                  <span className="text-xs text-gray-500 mt-1">Cloud storage</span>
                  {storageType === 's3' && (
                    <CheckCircle className="absolute top-2 right-2 w-5 h-5 text-primary-500" />
                  )}
                </button>

                {/* Local Option */}
                <button
                  type="button"
                  onClick={() => setStorageType('local')}
                  className={`relative flex flex-col items-center p-4 border-2 rounded-lg transition-all ${
                    storageType === 'local'
                      ? 'border-primary-500 bg-primary-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <HardDrive
                    className={`w-8 h-8 mb-2 ${
                      storageType === 'local' ? 'text-primary-500' : 'text-gray-400'
                    }`}
                  />
                  <span
                    className={`font-medium ${
                      storageType === 'local' ? 'text-primary-700' : 'text-gray-700'
                    }`}
                  >
                    Local Storage
                  </span>
                  <span className="text-xs text-gray-500 mt-1">Server filesystem</span>
                  {storageType === 'local' && (
                    <CheckCircle className="absolute top-2 right-2 w-5 h-5 text-primary-500" />
                  )}
                </button>
              </div>
            </div>

            {/* Conditional Fields */}
            {storageType === 'local' && (
              <div className="space-y-2">
                <label
                  htmlFor="localPath"
                  className="block text-sm font-medium text-gray-700"
                >
                  Local Storage Path
                </label>
                <input
                  id="localPath"
                  type="text"
                  value={localPath}
                  onChange={(e) => setLocalPath(e.target.value)}
                  placeholder="/data/heliograph/documents"
                  className={`w-full px-4 py-2.5 border rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 ${
                    pathError ? 'border-red-300' : 'border-gray-300'
                  }`}
                />
                {pathError && (
                  <p className="text-sm text-red-600 flex items-center gap-1">
                    <AlertCircle className="w-4 h-4" />
                    {pathError}
                  </p>
                )}
                <p className="text-xs text-gray-500">
                  Must be an absolute path starting with: {ALLOWED_PATH_PREFIXES.join(', ')}
                </p>
              </div>
            )}

            {storageType === 's3' && (
              <div className="space-y-2">
                <label
                  htmlFor="bucket"
                  className="block text-sm font-medium text-gray-700"
                >
                  S3 Bucket (Optional)
                </label>
                <input
                  id="bucket"
                  type="text"
                  value={bucket}
                  onChange={(e) => setBucket(e.target.value)}
                  placeholder="Leave empty to use default bucket"
                  className="w-full px-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                />
                <p className="text-xs text-gray-500">
                  Optionally specify a custom S3 bucket. Leave empty to use the system default.
                </p>
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="px-6 py-4 bg-gray-50 border-t rounded-b-lg flex items-center justify-between">
            <p className="text-sm text-gray-500">
              {hasChanges ? 'You have unsaved changes' : 'All changes saved'}
            </p>
            <button
              onClick={handleSave}
              disabled={isSaving || !hasChanges || (storageType === 'local' && !!pathError)}
              className="flex items-center gap-2 px-4 py-2 bg-primary-500 hover:bg-primary-600 text-white font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSaving ? (
                <>
                  <Loader className="w-4 h-4 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Save className="w-4 h-4" />
                  Save Changes
                </>
              )}
            </button>
          </div>
        </div>

        {/* Info Card */}
        <div className="mt-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <h3 className="font-medium text-blue-800 mb-2">About Storage Options</h3>
          <ul className="text-sm text-blue-700 space-y-1">
            <li>
              <strong>Amazon S3:</strong> Cloud-based storage with high availability and durability.
              Recommended for production use.
            </li>
            <li>
              <strong>Local Storage:</strong> Store documents on the server filesystem. Useful for
              development or air-gapped environments.
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
}
