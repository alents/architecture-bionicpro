import React, { useState } from 'react';
import { useAuth } from '../useAuth';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const ReportPage: React.FC = () => {
  const { authenticated, loading, login } = useAuth();
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const downloadReport = async () => {
    try {
      setDownloading(true);
      setError(null);

      const response = await fetch(`${API_URL}/api/reports`, {
        credentials: 'include',
      });

      if (response.status === 401) {
        login(); // сессия протухла — на логин
        return;
      }

      if (!response.ok) {
        throw new Error('Failed to fetch report');
      }

      // Обработка ответа — например скачивание файла
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'report.xlsx';
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setDownloading(false);
    }
  };

  if (loading) {
    return <div>Loading...</div>;
  }

  if (!authenticated) {
    return (
        <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
          <button
              onClick={login}
              className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
          >
            Login
          </button>
        </div>
    );
  }

  return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
        <div className="p-8 bg-white rounded-lg shadow-md">
          <h1 className="text-2xl font-bold mb-6">Usage Reports</h1>

          <button
              onClick={downloadReport}
              disabled={downloading}
              className={`px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 ${
                  downloading ? 'opacity-50 cursor-not-allowed' : ''
              }`}
          >
            {downloading ? 'Generating Report...' : 'Download Report'}
          </button>

          {error && (
              <div className="mt-4 p-4 bg-red-100 text-red-700 rounded">
                {error}
              </div>
          )}
        </div>
      </div>
  );
};

export default ReportPage;