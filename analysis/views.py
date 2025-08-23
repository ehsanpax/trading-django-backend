from rest_framework import generics, status, views
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
# from rest_framework.authentication import TokenAuthentication # If using DRF's TokenAuthentication
# from misc.utils import token_required # If using the custom decorator from misc/utils.py. Needs to be moved to a shared location.

from .models import Instrument, AnalysisJob, AnalysisResult
from .serializers import (
    InstrumentSerializer,
    AnalysisJobSubmitSerializer,
    AnalysisJobStatusSerializer,
    AnalysisResultSerializer,
    InstrumentCreateSerializer, # Added
)
from .tasks import run_analysis_job_task, fetch_missing_instrument_data_task, download_initial_history_task, ANALYSIS_MODULE_MAPPING # Added download_initial_history_task
from datetime import datetime, timedelta # Added
from django.utils import timezone # Added for timezone.now()
import importlib

# Note: For token authentication, you'll need to choose one method.
# If using DRF's built-in TokenAuthentication, ensure it's in DEFAULT_AUTHENTICATION_CLASSES in settings.
# If using the custom decorator, it should be moved to a more central 'utils' app or similar.
# For now, relying on global DEFAULT_AUTHENTICATION_CLASSES and IsAuthenticated.

class InstrumentListView(generics.ListCreateAPIView): # Changed to ListCreateAPIView
    queryset = Instrument.objects.all()
    # serializer_class = InstrumentSerializer # Will use get_serializer_class
    permission_classes = [IsAuthenticated]
    # authentication_classes = [TokenAuthentication] # Example if overriding default

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return InstrumentCreateSerializer
        return InstrumentSerializer

    def create(self, request, *args, **kwargs):
        # Extract symbol first to check existence
        symbol_from_request = request.data.get('symbol')
        if not symbol_from_request:
            return Response({"symbol": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
        
        symbol_upper = symbol_from_request.upper()

        try:
            instrument = Instrument.objects.get(symbol=symbol_upper)
            # Instrument already exists, use InstrumentCreateSerializer to validate incoming update data
            # Pass instance=instrument to update it
            update_serializer = InstrumentCreateSerializer(instrument, data=request.data, partial=True) # partial=True allows partial updates
            update_serializer.is_valid(raise_exception=True) # Validate incoming data against serializer rules
            
            # Logic for deciding if an update/download is needed
            needs_update = False
            if instrument.data_status in [Instrument.DATA_STATUS_CHOICES[0][0], Instrument.DATA_STATUS_CHOICES[3][0]]: # PENDING or ERROR
                needs_update = True
            elif instrument.last_updated and instrument.last_updated < timezone.now() - timedelta(days=7): # Data is old
                needs_update = True
            # Or if any relevant field like exchange, base_timeframe is changing
            if update_serializer.validated_data.get('exchange') and update_serializer.validated_data.get('exchange') != instrument.exchange:
                needs_update = True # If exchange changes, new data might be needed
            if update_serializer.validated_data.get('base_timeframe') and update_serializer.validated_data.get('base_timeframe') != instrument.base_timeframe:
                needs_update = True # If base timeframe changes, new data is definitely needed

            if needs_update:
                instrument.data_status = 'UPDATING'
                # Apply updates from serializer.validated_data
                instrument.exchange = update_serializer.validated_data.get('exchange', instrument.exchange)
                instrument.base_timeframe = update_serializer.validated_data.get('base_timeframe', instrument.base_timeframe)
                instrument.is_major = update_serializer.validated_data.get('is_major', instrument.is_major)
                instrument.save() # Save changes before triggering task

                default_start_date = (datetime.now() - timedelta(days=2*365)).strftime('%Y-%m-%d')
                download_initial_history_task.delay(instrument.symbol, default_start_date)
                
                response_serializer = InstrumentSerializer(instrument) # Use the display serializer
                return Response({
                    "message": f"Instrument {instrument.symbol} already exists. Data update initiated.",
                    "instrument": response_serializer.data
                }, status=status.HTTP_200_OK)
            elif instrument.data_status == 'UPDATING':
                response_serializer = InstrumentSerializer(instrument)
                return Response({
                    "message": f"Instrument {instrument.symbol} already exists and is currently updating.",
                    "instrument": response_serializer.data
                }, status=status.HTTP_200_OK)
            else: # AVAILABLE and recent, and no significant fields changed
                # Still, apply any minor updates like 'is_major' if they were sent
                instrument.is_major = update_serializer.validated_data.get('is_major', instrument.is_major)
                instrument.save(update_fields=['is_major', 'updated_at'] if 'is_major' in update_serializer.validated_data else ['updated_at'])

                response_serializer = InstrumentSerializer(instrument)
                return Response({
                    "message": f"Instrument {instrument.symbol} already exists and is up-to-date. Minor fields updated if provided.",
                    "instrument": response_serializer.data
                }, status=status.HTTP_200_OK)

        except Instrument.DoesNotExist:
            # Instrument does not exist, proceed with creation using InstrumentCreateSerializer
            create_serializer = InstrumentCreateSerializer(data=request.data)
            create_serializer.is_valid(raise_exception=True)
            instrument = create_serializer.save() # This will call serializer.create()
            
            default_start_date = (datetime.now() - timedelta(days=2*365)).strftime('%Y-%m-%d')
            download_initial_history_task.delay(instrument.symbol, default_start_date)
            
            # Use InstrumentSerializer for the response to show full data including status
            response_serializer = InstrumentSerializer(instrument)
            headers = self.get_success_headers(response_serializer.data)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

class AnalysisSubmitView(views.APIView):
    permission_classes = [IsAuthenticated]
    # authentication_classes = [TokenAuthentication]

    def post(self, request, *args, **kwargs):
        serializer = AnalysisJobSubmitSerializer(data=request.data)
        if serializer.is_valid():
            validated_data = serializer.validated_data
            try:
                instrument = Instrument.objects.get(symbol=validated_data['instrument_symbol'])
            except Instrument.DoesNotExist:
                # This case should ideally be caught by serializer validation, but as a safeguard:
                return Response({"error": f"Instrument '{validated_data['instrument_symbol']}' not found."}, status=status.HTTP_400_BAD_REQUEST)

            job = AnalysisJob.objects.create(
                user=request.user,
                instrument=instrument,
                name=validated_data.get('name'),
                analysis_type=validated_data['analysis_type'],
                target_timeframe=validated_data['target_timeframe'],
                start_date=validated_data['start_date'],
                end_date=validated_data['end_date'],
                indicator_configs=validated_data.get('indicator_configs', []),
                analysis_params=validated_data.get('analysis_params', {}),
                status='PENDING' # Initial status
            )

            response_data = {
                "job_id": job.job_id,
                "status": job.status,
            }

            if instrument.data_status in ['PENDING_INITIAL_DOWNLOAD', 'ERROR']:
                job.status = 'FETCHING_DATA'
                job.save()
                # Pass job_id as string to Celery task
                fetch_missing_instrument_data_task.delay(instrument.symbol, str(job.job_id)) 
                response_data["status"] = job.status
                response_data["message"] = "Data not available for instrument, fetching now. Analysis will start once data is ready."
                return Response(response_data, status=status.HTTP_202_ACCEPTED)
            else:
                # Data is 'AVAILABLE' or 'UPDATING'
                # For 'UPDATING', we might still proceed, or queue it after update. For now, proceed.
                run_analysis_job_task.delay(str(job.job_id)) # Pass job_id as string
                response_data["message"] = "Analysis job submitted."
                return Response(response_data, status=status.HTTP_202_ACCEPTED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class AnalysisJobStatusView(generics.RetrieveUpdateDestroyAPIView):
    queryset = AnalysisJob.objects.all()
    serializer_class = AnalysisJobStatusSerializer
    permission_classes = [IsAuthenticated]
    # authentication_classes = [TokenAuthentication]
    lookup_field = 'job_id'

class AnalysisResultView(generics.RetrieveAPIView):
    serializer_class = AnalysisResultSerializer
    permission_classes = [IsAuthenticated]
    # authentication_classes = [TokenAuthentication]
    lookup_field = 'job_id' # This will be job__job_id due to OneToOneField relation

    def get_queryset(self):
        # Filter for results where the job was successful
        return AnalysisResult.objects.filter(job__status='COMPLETED_SUCCESS')

    def get_object(self):
        # Override get_object to look up by job_id on the AnalysisJob model
        # then retrieve the related AnalysisResult.
        queryset = self.get_queryset()
        job_id = self.kwargs.get(self.lookup_field)
        try:
            # We are looking for AnalysisResult whose job's job_id matches
            obj = queryset.get(job__job_id=job_id)
            self.check_object_permissions(self.request, obj.job) # Check permissions on the job object
            return obj
        except AnalysisResult.DoesNotExist:
            # Check if the job exists but is not completed successfully or has no result
            try:
                job = AnalysisJob.objects.get(job_id=job_id)
                if job.status != 'COMPLETED_SUCCESS':
                     raise generics.NotFound(detail=f"Results not available yet. Job status: {job.status}.")
                else:
                    # Job is COMPLETED_SUCCESS but no AnalysisResult (should not happen if logic is correct)
                    raise generics.NotFound(detail="Results not found for this job.")
            except AnalysisJob.DoesNotExist:
                 raise generics.NotFound(detail="Job not found.")

class AnalysisJobListView(generics.ListAPIView):
    serializer_class = AnalysisJobStatusSerializer # Re-use this serializer for listing job details
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Return jobs for the current authenticated user, ordered by creation date
        return AnalysisJob.objects.filter(user=self.request.user).order_by('-created_at')

class AnalysisTypeListView(views.APIView):
    """
    A view to get the list of available analysis types.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        analysis_types = [
            {"value": choice[0], "label": choice[1]}
            for choice in AnalysisJob.ANALYSIS_TYPE_CHOICES
        ]
        return Response(analysis_types)

class AnalysisTypeDetailView(views.APIView):
    """
    A view to get the details of a specific analysis type, including required indicators.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, analysis_type_name, *args, **kwargs):
        analysis_module_name = ANALYSIS_MODULE_MAPPING.get(analysis_type_name)
        if not analysis_module_name:
            return Response({"error": "Analysis type not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            module_path = f"analysis.core_analysis.{analysis_module_name}"
            analysis_module = importlib.import_module(module_path)
            required_indicators = getattr(analysis_module, 'REQUIRED_INDICATORS', [])
            return Response(required_indicators)
        except (ImportError, AttributeError):
            return Response({"error": "Could not retrieve analysis details."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
